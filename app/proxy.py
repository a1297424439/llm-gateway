# -*- coding: utf-8 -*-
"""自动代理决策：按渠道判断该不该走代理。

判断顺序（优先级从高到低）：
1. 手动覆盖：渠道有 proxy 字段（非空字符串或布尔）→ 直接用它，不探测。
2. 规则快判：命中「海外域名名单」→ 走全局代理，不探测（确定性场景零误判）。
3. 探测兜底（名单外的未知域名，默认直连）：
   - 首次见到该域名：同步探测一次（2 秒超时），用结果决定本次走向。
   - 探测结果带非对称 TTL：直连通缓存 10 分钟；直连不通只缓存 30 秒
     （瞬时网络抖动的误判最多影响 30 秒，过期自动重探自愈）。
   - TTL 过期后的重探在后台异步进行（stale-while-revalidate）：请求先用旧
     结论立即出发，不被 2 秒探测阻塞。
   - 连续 3 天探测直连都失败（期间任何一次成功都清零重来）→ 记为「永久走
     代理」，持久化到磁盘（重启不丢、不再探测）。想解除：在设置页改一次
     代理地址（会清空探测缓存）。

代理出口（全局配置 proxy.url）由本机代理（如 UniClash）提供，端口可配。
"""
import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config as cfgmod

# 海外域名名单（命中即走代理，无需探测；主机名等于名单项或为其子域名）
OVERSEAS_DOMAINS = (
    "api.b.ai",
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "openrouter.ai",
    "api.groq.com",
    "api.x.ai",
    "api.mistral.ai",
    "api.together.xyz",
)

# 非对称 TTL
TTL_OK = 600.0                 # 直连通缓存 10 分钟
TTL_FAIL = 30.0                # 直连不通只缓存 30 秒（抖动快速自愈）
PERMANENT_AFTER = 3 * 86400.0  # 连续 3 天直连失败 → 永久走代理

_cache: dict = {}    # host -> {"direct": bool, "ts": float, "permanent": bool}
_streaks: dict = {}  # host -> {"first": float, "last": float}（连续失败窗口）
_inflight: set = set()
_lock = threading.Lock()
_loaded = False
_last_save = 0.0

_PROXY_CLIENT: httpx.AsyncClient | None = None
_proxy_url_cache: str | None = None


def _state_file() -> Path:
    """探测缓存持久化文件（与 config.json 同目录，重启不丢）。"""
    return Path(cfgmod.config_path()).parent / "proxy_state.json"


def _ensure_loaded():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        _cache.update(data.get("cache") or {})
        _streaks.update(data.get("streaks") or {})
    except Exception:
        pass


def _persist():
    global _last_save
    now = time.time()
    if now - _last_save < 5:   # 轻量去抖，避免高频重探时反复写盘
        return
    _last_save = now
    try:
        _state_file().write_text(
            json.dumps({"cache": _cache, "streaks": _streaks}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def proxy_url() -> str:
    """全局代理地址（空字符串=全直连）。

    解析优先级：
    1. 手动配置 proxy.url 非空 → 直接用（手动覆盖最高优先）。
    2. proxy.url 为空 → 自动读 Windows 系统代理（注册表 ProxyServer），
       任何代理软件（Clash Verge/UniClash/V2rayN/SSTAP 等）开了「系统代理」
       都会写这个键，从而自动拿到正确端口，不依赖具体软件。
    3. 都没有 → 返回空（全直连）。
    """
    try:
        u = (cfgmod.cfg().get("proxy") or {}).get("url") or ""
        u = str(u).strip()
        if u:
            return u
    except Exception:
        pass

    # 自动探测 Windows 系统代理（仅 Windows）
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            enabled, _ = winreg.QueryValueEx(k, "ProxyEnable")
            if enabled:
                server, _ = winreg.QueryValueEx(k, "ProxyServer")
                server = str(server).strip()
                if server:
                    if "=" in server:  # 形如 "http=127.0.0.1:7890;https=..."
                        for part in server.split(";"):
                            if part.strip().lower().startswith("http="):
                                server = part.split("=", 1)[1].strip()
                                break
                    if server and "://" not in server:
                        server = "http://" + server
                    return server
    except Exception:
        pass

    return ""


def _overseas(host: str) -> bool:
    host = (host or "").lower()
    return any(host == d or host.endswith("." + d) for d in OVERSEAS_DOMAINS)


def _host_of(provider: dict) -> str:
    try:
        return urlparse(provider.get("base_url") or "").hostname or ""
    except Exception:
        return ""


def _record(host: str, ok: bool):
    """记录一次探测结果：成功清零连续失败窗口；失败累计，满 3 天转永久。"""
    now = time.time()
    with _lock:
        if ok:
            _streaks.pop(host, None)
            _cache[host] = {"direct": True, "ts": now, "permanent": False}
        else:
            st = _streaks.setdefault(host, {"first": now, "last": now})
            st["last"] = now
            permanent = (now - st["first"]) >= PERMANENT_AFTER
            _cache[host] = {"direct": False, "ts": now, "permanent": permanent}
        _persist()


def _probe_direct(host: str) -> bool:
    """直连探测：2 秒超时，能连上（TCP 443）即认为直连可用。"""
    try:
        s = socket.create_connection((host, 443), timeout=2)
        s.close()
        return True
    except Exception:
        return False


def _spawn_reprobe(host: str):
    """后台异步重探（stale-while-revalidate）：不阻塞当前请求。"""
    with _lock:
        if host in _inflight:
            return
        _inflight.add(host)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无事件循环（同步上下文/测试）：退化为同步探测
        with _lock:
            _inflight.discard(host)
        _record(host, _probe_direct(host))
        return

    async def _job():
        try:
            ok = await loop.run_in_executor(None, _probe_direct, host)
            _record(host, ok)
        finally:
            with _lock:
                _inflight.discard(host)

    loop.create_task(_job())


def should_use_proxy(provider: dict) -> bool:
    """渠道是否应走代理（手动 > 名单 > 探测[TTL+永久]）。"""
    # 1. 手动覆盖
    p = provider.get("proxy")
    if isinstance(p, str) and p.strip():
        return True
    if isinstance(p, bool):
        return bool(p)

    host = _host_of(provider)
    if not host:
        return False

    # 2. 规则快判：海外名单
    if _overseas(host):
        return True

    # 3. 探测兜底（带非对称 TTL + 永久判定 + 后台重探）
    _ensure_loaded()
    now = time.time()
    with _lock:
        e = _cache.get(host)
        if e is not None:
            if e.get("permanent"):
                return not e["direct"]          # 永久结论直接用，不再探测
            ttl = TTL_OK if e["direct"] else TTL_FAIL
            if now - e["ts"] <= ttl:
                return not e["direct"]          # 未过期，用缓存
    if e is None:
        # 首次见到该域名：同步探测一次（≤2s，仅此一次）
        ok = _probe_direct(host)
        _record(host, ok)
        return not ok
    # 过期：先用旧结论立即返回，后台重探自愈
    _spawn_reprobe(host)
    return not e["direct"]


def client_for(provider: dict, direct_client):
    """返回该渠道应使用的 AsyncClient（直连 direct_client 或代理 PROXY_CLIENT）。"""
    global _PROXY_CLIENT, _proxy_url_cache

    if not should_use_proxy(provider):
        return direct_client

    url = proxy_url()
    if not url:
        return direct_client  # 未配代理 → 直连兜底

    if _PROXY_CLIENT is None or _proxy_url_cache != url:
        if _PROXY_CLIENT is not None:
            try:
                _PROXY_CLIENT.aclose()
            except Exception:
                pass
        _PROXY_CLIENT = httpx.AsyncClient(
            proxies=url,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
            timeout=httpx.Timeout(connect=15, read=120, write=60, pool=10),
        )
        _proxy_url_cache = url

    return _PROXY_CLIENT


def invalidate_probe_cache():
    """清空探测缓存并清盘（设置页修改代理时调用；这也是解除「永久」的入口）。"""
    with _lock:
        _cache.clear()
        _streaks.clear()
        try:
            _state_file().write_text("{}", encoding="utf-8")
        except Exception:
            pass


async def close_proxy():
    """关闭代理客户端（lifespan 结束时调用）。"""
    global _PROXY_CLIENT, _proxy_url_cache
    if _PROXY_CLIENT is not None:
        try:
            await _PROXY_CLIENT.aclose()
        except Exception:
            pass
        _PROXY_CLIENT = None
        _proxy_url_cache = None
