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
USAGE: Dict[str, dict] = {}   # 按天累计 token 用量（热力图数据源），key = "YYYY-MM-DD"
SPEED: Dict[str, dict] = {}   # 测速结果，key = "{provider_id}::{model}" → {ms, ok, status, ts}
THINK_EFFORT: Dict[str, str] = {}   # 学到的思考强度词表覆盖，key = "{provider_id}::{model}" → 上游认的 effort 值
POOL: Dict[str, dict] = {}   # key = "{provider_id}::{model}"  模型级冷却
PPOOL: Dict[str, dict] = {}  # key = provider_id                  渠道级冷却（额度类错误）
_dirty = False
# 不入用量的「诊断类」日志别名（模型列表刷新等，不是真实对话请求）
_USAGE_SKIP_ALIAS = ("模型列表",)

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


def cooling_enabled() -> bool:
    """冷却机制总开关（config.cooldown.enabled，默认 True）。

    关闭后：失败不再写入冷却池，每次请求都按候选顺序全量重试（轮询式），
    适合「上游偶发抖动、宁可多试也不要被冻住」的场景；代价是真正失效的
    渠道（如 key 失效）每次请求都会白撞一次。
    """
    try:
        cd = (cfgmod.cfg() or {}).get("cooldown") or {}
        v = cd.get("enabled")
        return True if v is None else bool(v)
    except Exception:
        return True


def log_request(**kw) -> None:
    global _dirty
    entry = {"ts": time.time()}
    entry.update(kw)
    with MUTEX:
        LOGS.append(entry)
        _dirty = True
    # 顺带累计当日 token 用量（热力图数据源）：
    # usage 可能是 int（历史调用点只给 prompt_tokens）或 {"p":..,"c":..}（流式 usage_box）
    if str(entry.get("alias") or "") not in _USAGE_SKIP_ALIAS:
        u = entry.get("usage")
        pt = ct = 0
        if isinstance(u, dict):
            pt = int(u.get("p") or u.get("prompt_tokens") or 0)
            ct = int(u.get("c") or u.get("completion_tokens") or 0)
        elif isinstance(u, (int, float)):
            pt = int(u)
        add_usage(pt, ct, ok=bool(entry.get("ok")))


def _day_key(ts: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts if ts is not None else time.time()))


def add_usage(prompt: int = 0, completion: int = 0, ok: bool = True, ts: Optional[float] = None) -> None:
    """按天累计 token 用量（「Token 消耗热力图」数据源）。

    与 500 条滚动日志解耦：日志会被挤掉，这里按天累加并持久化，长期保留。
    """
    global _dirty
    key = _day_key(ts)
    with MUTEX:
        d = USAGE.setdefault(key, {"p": 0, "c": 0, "n": 0, "ok": 0, "fail": 0})
        d["p"] = int(d.get("p", 0)) + max(0, int(prompt or 0))
        d["c"] = int(d.get("c", 0)) + max(0, int(completion or 0))
        d["n"] = int(d.get("n", 0)) + 1
        k = "ok" if ok else "fail"
        d[k] = int(d.get(k, 0)) + 1
        _dirty = True


def usage_days(limit: int = 200) -> List[dict]:
    """按日期升序返回每日用量（热力图）；total = prompt + completion。"""
    with MUTEX:
        items = sorted(USAGE.items())[-limit:]
        out = []
        for day, v in items:
            p = int(v.get("p", 0))
            c = int(v.get("c", 0))
            out.append({"day": day, "p": p, "c": c, "total": p + c,
                        "n": int(v.get("n", 0)), "ok": int(v.get("ok", 0)),
                        "fail": int(v.get("fail", 0))})
    return out


def usage_total(days: Optional[List[dict]] = None) -> dict:
    """汇总（可传 usage_days() 结果避免重复加锁）：总量 / 今日 / 近 7 天。"""
    ds = days if days is not None else usage_days(400)
    today = _day_key()
    tot = {"p": 0, "c": 0, "total": 0, "n": 0, "days": len(ds)}
    for d in ds:
        tot["p"] += int(d["p"]); tot["c"] += int(d["c"])
        tot["total"] += int(d["total"]); tot["n"] += int(d["n"])
    today_row = next((d for d in ds if d["day"] == today), None)
    last7 = ds[-7:]
    return {
        "today": today_row or {"day": today, "p": 0, "c": 0, "total": 0, "n": 0, "ok": 0, "fail": 0},
        "last7": {"p": sum(d["p"] for d in last7), "c": sum(d["c"] for d in last7),
                  "total": sum(d["total"] for d in last7), "n": sum(d["n"] for d in last7)},
        "all": tot,
    }


def set_speeds(results, ts: Optional[float] = None) -> None:
    """记录一轮测速结果（key = 渠道ID::模型），供「速度优先」排序与面板展示。"""
    global _dirty
    t = float(ts or time.time())
    with MUTEX:
        for r in (results or []):
            try:
                pid = str(r.get("provider_id") or "")
                m = str(r.get("model") or "")
                if not pid or not m:
                    continue
                SPEED[f"{pid}::{m}"] = {"ms": int(r.get("ms") or 0), "ok": bool(r.get("ok")),
                                        "status": int(r.get("status") or 0), "ts": t}
            except Exception:
                continue
        if len(SPEED) > 800:   # 只保留最近 800 条，防止无限增长
            for k in sorted(SPEED, key=lambda k: SPEED[k].get("ts", 0))[:len(SPEED) - 800]:
                SPEED.pop(k, None)
        _dirty = True


def speed_snapshot() -> Dict[str, dict]:
    """全部测速结果快照（面板用）。"""
    with MUTEX:
        return {k: dict(v) for k, v in SPEED.items()}


def set_think_effort(provider_id: str, model: str, effort: str) -> None:
    """记住「这个渠道 + 这个模型」上游认的 reasoning_effort 取值（学习结果，持久化）。

    上游词表不一致（OpenAI: low/medium/high；部分中转的 qwen3.8: xhigh/medium/low），
    发错值会硬 400。学到之后写在这里，重启后依然生效，避免反复白撞 400。
    """
    global _dirty
    pid = str(provider_id or "")
    m = str(model or "")
    e = str(effort or "").strip()
    if not pid or not m or not e:
        return
    with MUTEX:
        THINK_EFFORT[f"{pid}::{m}"] = e
        if len(THINK_EFFORT) > 800:
            for k in list(THINK_EFFORT)[:-800]:
                THINK_EFFORT.pop(k, None)
        _dirty = True


def think_effort_of(provider_id: str, model: str) -> str:
    """取该渠道+模型学到的 effort 覆盖值（没有则空串）。"""
    pid = str(provider_id or "")
    m = str(model or "")
    if not pid or not m:
        return ""
    with MUTEX:
        return str(THINK_EFFORT.get(f"{pid}::{m}") or "")


def speed_of(provider_id: str, model: str) -> Optional[int]:
    """该 (渠道, 模型) 最近一次「成功」测速的耗时（毫秒）；没测过/失败 = None（排序时排最后）。"""
    if not provider_id or not model:
        return None
    with MUTEX:
        v = SPEED.get(f"{provider_id}::{model}")
    if not v or not v.get("ok"):
        return None
    try:
        return int(v.get("ms") or 0) or None
    except Exception:
        return None


def mark_fail(key: str, base: float, maxs: float, retry_after: Optional[float] = None, error: str = "") -> None:
    """失败进入冷却池：指数退避 base*2^(n-1)，429 优先尊重 Retry-After。"""
    global _dirty
    if not cooling_enabled():
        return
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
    if not cooling_enabled():
        return
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
    if not cooling_enabled():
        return False, 0.0
    it = PPOOL.get(provider_id)
    if not it:
        return False, 0.0
    rem = float(it.get("until", 0)) - time.time()
    if rem <= 0:
        return False, 0.0
    return True, rem


def provider_probeable(provider_id: str, ratio: float = 0.2) -> bool:
    """渠道冷却是否进入「半开试探期」：剩余时间已不足冷却总时长的 ratio 比例。

    用于让实际已恢复的渠道自愈——冷却接近尾声时放一个真实请求进去试探，
    成功即解除（provider_mark_success），失败则继续退避。默认 ratio=0.2，
    即冷却进行到 80% 之后允许试探。
    """
    it = PPOOL.get(provider_id)
    if not it:
        return True
    until = float(it.get("until", 0))
    opened = float(it.get("opened_at", 0))
    delay = float(it.get("delay", 0))
    now = time.time()
    if now >= until:
        return True
    # 无打开时间/无时长信息时保守不允许
    if not delay or delay <= 0:
        return False
    return (now - opened) >= (delay * (1.0 - ratio))


def provider_mark_success(provider_id: str) -> None:
    """渠道请求成功 → 解除该渠道的渠道级冷却。"""
    global _dirty
    with MUTEX:
        if provider_id in PPOOL:
            PPOOL.pop(provider_id, None)
            _dirty = True


def blocked(key: str):
    """是否仍在冷却中。冷却到期后半开：允许一次试探请求，再失败则加倍冷却。"""
    if not cooling_enabled():
        return False, 0.0
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
        data = {"logs": list(LOGS)[-500:], "pool": dict(POOL), "ppool": dict(PPOOL),
                "usage": {k: dict(v) for k, v in sorted(USAGE.items())[-400:]},
                "speed": {k: dict(v) for k, v in SPEED.items()},
                "think_effort": dict(THINK_EFFORT)}
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
    _backfill = False
    with MUTEX:
        for l in (data.get("logs") or [])[-500:]:
            try:
                LOGS.append(l)
            except Exception:
                pass
        # 冷启动回填：老版本没有 usage 天表，先把现有日志里的 token 归到各自日期，
        # 这样热力图一上线就有历史痕迹，而不是从零开始。
        if not USAGE:
            _backfill = True
        for k, v in (data.get("pool") or {}).items():
            if isinstance(v, dict) and float(v.get("until", 0)) > now:
                POOL[k] = v
    if _backfill:
        for l in (data.get("logs") or [])[-500:]:
            if not isinstance(l, dict) or str(l.get("alias") or "") in _USAGE_SKIP_ALIAS:
                continue
            u = l.get("usage")
            pt = ct = 0
            if isinstance(u, dict):
                pt = int(u.get("p") or u.get("prompt_tokens") or 0)
                ct = int(u.get("c") or u.get("completion_tokens") or 0)
            elif isinstance(u, (int, float)):
                pt = int(u)
            try:
                add_usage(pt, ct, ok=bool(l.get("ok")), ts=float(l.get("ts") or now))
            except Exception:
                pass
    with MUTEX:
        for k, v in (data.get("ppool") or {}).items():
            if isinstance(v, dict) and float(v.get("until", 0)) > now:
                PPOOL[k] = v
        for k, v in (data.get("speed") or {}).items():
            if isinstance(v, dict):
                SPEED[k] = {"ms": int(v.get("ms") or 0), "ok": bool(v.get("ok")),
                            "status": int(v.get("status") or 0), "ts": float(v.get("ts") or 0)}
        for k, v in (data.get("usage") or {}).items():
            if isinstance(v, dict):
                USAGE[str(k)] = {"p": int(v.get("p", 0) or 0), "c": int(v.get("c", 0) or 0),
                                 "n": int(v.get("n", 0) or 0), "ok": int(v.get("ok", 0) or 0),
                                 "fail": int(v.get("fail", 0) or 0)}
        for k, v in (data.get("think_effort") or {}).items():
            if isinstance(v, str) and v:
                THINK_EFFORT[str(k)] = v


def maybe_persist() -> None:
    global _dirty
    if _dirty:
        with MUTEX:
            _dirty = False
        try:
            persist()
        except Exception:
            pass
