"""配置持久化：随机地址(端口)/Key 生成、JSON 原子写入。

存储位置：
  Windows : %APPDATA%\\LLMGateway\\config.json
  Linux   : ~/.config/llm-gateway/config.json
  可用环境变量 LLM_GATEWAY_HOME 覆盖（便携模式）。
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import socket
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

MUTEX = threading.RLock()
_CFG: Optional[dict] = None


def data_dir() -> Path:
    env = os.environ.get("LLM_GATEWAY_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "LLMGateway"
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "llm-gateway"


def config_path() -> Path:
    return data_dir() / "config.json"


def state_path() -> Path:
    return data_dir() / "state.json"


def new_key(history: Optional[List[str]] = None) -> str:
    """生成本地 API Key，保证与历史 Key 不重复。"""
    seen = set(history or [])
    for _ in range(1000):
        k = "sk-lg-" + secrets.token_hex(24)
        if k not in seen:
            return k
    raise RuntimeError("无法生成不重复的 Key")


def random_free_port(host: str = "127.0.0.1") -> int:
    """在本机挑一个随机空闲端口作为网关监听地址。"""
    for _ in range(200):
        port = 20000 + secrets.randbelow(40000)
        if _port_free(host, port):
            return port
    # 兜底：交给系统分配
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def defaults() -> dict:
    return {
        "version": 1,
        "mode": "smart",  # smart=智能路由 safe=安全路由
        "server": {
            "host": "127.0.0.1",       # 监听地址
            "port": 0,                  # 首次启动随机生成
            "key": "",                  # 首次启动随机生成
            "key_history": [],          # 历史密钥，保证不重复
            "lan_allowed": False,
            "close_action": "",         # 点 ✕ 的行为："hide"=隐藏到托盘 "quit"=退出程序 ""=每次询问
        },
        "routing": {
            "strategy": "site_first",   # site_first=网站优先 model_first=模型优先
            "max_attempts": 4,
            "timeout_seconds": 120,     # 连接/整体兜底超时
            "model_timeout_seconds": 90,  # 模型响应超时：超过即跳过该模型进冷却（默认90s覆盖99%正常响应）
            "whitelist_enabled": False,
            "whitelist": [],            # 有序：数组顺序即优先级
            "whitelist_fallback": True,  # 请求不在白名单时按白名单优先级回退
        },
        "cooldown": {"base_seconds": 300, "max_seconds": 3600,
                     "provider_base_seconds": 18000, "provider_max_seconds": 604800},
        "aggregate": {"name": "auto", "min_context": 1000000, "per_provider": 3},
        "providers": [],   # 渠道（网站 API）
        "aliases": [],     # 别名映射：统一模型名 -> [(provider, 上游模型, 优先级)]
    }


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    global _CFG
    with MUTEX:
        if _CFG is not None:
            return _CFG
        p = config_path()
        data: dict = {}
        if p.exists():
            try:
                data = json.loads(p.read_text("utf-8-sig"))
            except Exception:
                # 解析失败（BOM/半截写入等）：先备份原文件再回退默认，避免静默覆盖丢数据
                data = {}
                try:
                    from datetime import datetime
                    p.rename(p.with_name(p.name + ".bad-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
                except Exception:
                    pass
        cfg = _deep_merge(defaults(), data)
        changed = False
        if not cfg["server"].get("key"):
            cfg["server"]["key"] = new_key(cfg["server"].get("key_history"))
            cfg["server"].setdefault("key_history", []).append(cfg["server"]["key"])
            changed = True
        if not cfg["server"].get("port"):
            cfg["server"]["port"] = random_free_port(cfg["server"].get("host") or "127.0.0.1")
            changed = True
        if changed:
            _CFG = cfg
            save()
        else:
            _CFG = cfg
        return _CFG


def cfg() -> dict:
    return load()


def save() -> None:
    with MUTEX:
        if _CFG is None:
            return
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(_CFG, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, p)


def mutate(fn: Callable[[dict], object]):
    """在锁内修改配置并持久化；fn 的返回值透传。"""
    with MUTEX:
        c = load()
        ret = fn(c)
        save()
        return ret


def replace(new_cfg: dict) -> None:
    global _CFG
    with MUTEX:
        _CFG = new_cfg
        save()
