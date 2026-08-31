"""运行时状态：请求日志、冷却池（含指数退避）、统计；周期性持久化到 state.json。"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Dict, List, Optional

from . import config as cfgmod

MUTEX = threading.Lock()
LOGS: deque = deque(maxlen=500)
POOL: Dict[str, dict] = {}   # key = "{provider_id}::{model}"  模型级冷却
PPOOL: Dict[str, dict] = {}  # key = provider_id                  渠道级冷却（额度类错误）
_dirty = False

# 渠道级冷却参数（秒）：额度类错误触发。指数退避 5h → 10h → 20h → 40h → 80h → 160h，封顶 7 天。
PBASE_DEFAULT = 5 * 3600
PMAX_DEFAULT = 7 * 86400
# 限流类（429 非额度）渠道冷却：60s 起步指数退避，封顶 10 分钟。
PBASE_RATE = 60
PMAX_RATE = 600


def pbase_max(ctype: str = "quota") -> "tuple[float, float]":
    """渠道冷却参数。quota 允许 config.cooldown.provider_base_seconds / provider_max_seconds 覆盖；
    rate（429 限流）用固定短参数，不读配置。"""
    if ctype != "quota":
        return float(PBASE_RATE), float(PMAX_RATE)
    try:
        cd = (cfgmod.cfg() or {}).get("cooldown") or {}
        base = max(1, int(cd.get("provider_base_seconds") or PBASE_DEFAULT))
        maxs = max(base, int(cd.get("provider_max_seconds") or PMAX_DEFAULT))
        return float(base), float(maxs)
    except Exception:
        return float(PBASE_DEFAULT), float(PMAX_DEFAULT)


def log_request(**kw) -> None:
    global _dirty
    entry = {"ts": time.time()}
    entry.update(kw)
    with MUTEX:
        LOGS.append(entry)
        _dirty = True


def mark_fail(key: str, base: float, maxs: float, retry_after: Optional[float] = None, error: str = "") -> None:
    """失败进入冷却池：指数退避 base*2^(n-1)，429 优先尊重 Retry-After。"""
    global _dirty
    with MUTEX:
        it = POOL.setdefault(key, {"fails": 0, "opened_at": time.time()})
        it["fails"] = int(it.get("fails", 0)) + 1
        it["last_error"] = (error or "")[:300]
        if retry_after:
            delay = min(max(float(retry_after), base), maxs)
        else:
            delay = min(base * (2 ** (it["fails"] - 1)), maxs)
        it["delay"] = round(delay, 2)
        it["until"] = time.time() + delay
        _dirty = True


def mark_success(key: str) -> None:
    global _dirty
    with MUTEX:
        if key in POOL:
            POOL.pop(key, None)
            _dirty = True


def mark_provider_fail(provider_id: str, error: str = "", ctype: str = "quota") -> None:
    """渠道级冷却：整个渠道跳过。
    ctype="quota" → 额度类故障，长冷却：5h 起步指数退避，封顶 7 天。
    ctype="rate"  → 限流类故障，短冷却：60s 起步指数退避，封顶 10 分钟。
    quota 冷却优先：限流不得把额度冷却降级成短冷却。"""
    global _dirty
    with MUTEX:
        base, maxs = pbase_max(ctype)
        old = PPOOL.get(provider_id)
        if old and old.get("ctype") == "quota" and ctype == "rate":
            # 额度冷却中遇到限流：保留额度冷却，仅累计失败次数
            old["fails"] = int(old.get("fails", 0)) + 1
            old["last_error"] = (error or "")[:300]
            _dirty = True
            return
        it = PPOOL.setdefault(provider_id, {"fails": 0, "opened_at": time.time()})
        it["fails"] = int(it.get("fails", 0)) + 1
        it["last_error"] = (error or "")[:300]
        it["ctype"] = ctype
        delay = min(base * (2 ** (it["fails"] - 1)), maxs)
        it["delay"] = round(delay, 2)
        it["until"] = time.time() + delay
        _dirty = True


def provider_blocked(provider_id: str):
    """渠道是否在渠道级冷却中。返回 (是否冷却, 剩余秒)。"""
    it = PPOOL.get(provider_id)
    if not it:
        return False, 0.0
    rem = float(it.get("until", 0)) - time.time()
    if rem <= 0:
        return False, 0.0
    return True, rem


def provider_mark_success(provider_id: str) -> None:
    """渠道请求成功 → 解除该渠道的渠道级冷却。"""
    global _dirty
    with MUTEX:
        if provider_id in PPOOL:
            PPOOL.pop(provider_id, None)
            _dirty = True


def blocked(key: str):
    """是否仍在冷却中。冷却到期后半开：允许一次试探请求，再失败则加倍冷却。"""
    it = POOL.get(key)
    if not it:
        return False, 0.0
    rem = float(it.get("until", 0)) - time.time()
    if rem <= 0:
        return False, 0.0
    return True, rem


def clear(key: Optional[str] = None) -> None:
    global _dirty
    with MUTEX:
        if key:
            POOL.pop(key, None)
            PPOOL.pop(key, None)   # key 也可能是渠道 id（渠道冷却条目的「立即恢复」）
        else:
            POOL.clear()
            PPOOL.clear()
        _dirty = True


def clear_provider(provider_id: str) -> None:
    global _dirty
    with MUTEX:
        for k in [k for k in POOL if k.startswith(provider_id + "::")]:
            POOL.pop(k, None)
        PPOOL.pop(provider_id, None)
        _dirty = True


def snapshot(providers: List[dict]) -> List[dict]:
    name = {p.get("id"): p.get("name") for p in providers}
    now = time.time()
    out = []
    with MUTEX:
        items = [(k, dict(v)) for k, v in POOL.items()]
        pitems = [(k, dict(v)) for k, v in PPOOL.items()]
    for k, it in items:
        rem = float(it.get("until", 0)) - now
        if rem <= 0:
            continue
        pid, _, model = k.partition("::")
        out.append({
            "key": k,
            "provider_id": pid,
            "provider": name.get(pid, pid),
            "model": model,
            "remaining": round(rem),
            "delay": it.get("delay", 0),
            "fails": it.get("fails", 0),
            "last_error": it.get("last_error", ""),
        })
    for pid, it in pitems:
        rem = float(it.get("until", 0)) - now
        if rem <= 0:
            continue
        out.append({
            "key": pid,
            "provider_id": pid,
            "provider": name.get(pid, pid),
            "model": "（整个渠道）",
            "remaining": round(rem),
            "delay": it.get("delay", 0),
            "fails": it.get("fails", 0),
            "last_error": it.get("last_error", ""),
            "provider_level": True,
            "ctype": it.get("ctype", "quota"),
        })
    out.sort(key=lambda x: x["remaining"])
    return out


def stats() -> dict:
    with MUTEX:
        total = len(LOGS)
        ok = sum(1 for l in LOGS if l.get("ok"))
    return {
        "total": total,
        "success": ok,
        "failed": total - ok,
        "success_rate": round(ok / total * 100, 1) if total else 100.0,
    }


def persist() -> None:
    with MUTEX:
        data = {"logs": list(LOGS)[-500:], "pool": dict(POOL), "ppool": dict(PPOOL)}
    p = cfgmod.state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    os.replace(tmp, p)


def load() -> None:
    p = cfgmod.state_path()
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception:
        return
    now = time.time()
    with MUTEX:
        for l in (data.get("logs") or [])[-500:]:
            try:
                LOGS.append(l)
            except Exception:
                pass
        for k, v in (data.get("pool") or {}).items():
            if isinstance(v, dict) and float(v.get("until", 0)) > now:
                POOL[k] = v
        for k, v in (data.get("ppool") or {}).items():
            if isinstance(v, dict) and float(v.get("until", 0)) > now:
                PPOOL[k] = v


def maybe_persist() -> None:
    global _dirty
    if _dirty:
        with MUTEX:
            _dirty = False
        try:
            persist()
        except Exception:
            pass
