"""智能路由调度：按渠道档位（优先级）在勾选的 (渠道, 模型) 组合间调度。

不再有别名/映射：客户端直接请求上游模型名，凡是被勾选参与调度的渠道都会
按 档位优先级 依次尝试；失败进冷却池，自动落到下一个渠道。同名模型在多个
渠道被勾选时即天然互备。

两个增强（v2）：
  · 星标模型（config.stars）：无视冷却池，每次请求都排在最前面先试；全部失败后
    才回到正常调度（含冷却池）。顺序同样按「渠道档位 → 渠道内模型顺序」。
  · 速度优先（config.speed_first.enabled）：同一渠道内已勾选的模型按最近一次
    测速耗时从快到慢排序（没测到数据的排最后、保持原顺序）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Candidate:
    provider: dict
    model: str
    entry_priority: int = 1
    star: bool = False          # 星标：跳过冷却检查，每次最先尝试

    @property
    def key(self) -> str:
        return f"{self.provider['id']}::{self.model}"


@dataclass
class Selection:
    ok: bool
    code: int = 200
    message: str = ""
    alias: str = ""
    candidates: List[Candidate] = field(default_factory=list)


def _stars(cfg: dict) -> set:
    """星标集合：{"渠道ID::模型", ...}"""
    return {str(s).strip() for s in (cfg.get("stars") or []) if str(s).strip()}


def _speed_first_on(cfg: dict) -> bool:
    sf = cfg.get("speed_first")
    return bool(isinstance(sf, dict) and sf.get("enabled"))


def _ordered_models(p: dict, speed_first: bool) -> List[str]:
    """渠道内模型顺序；速度优先开启时按实测耗时升序（无数据排最后，保持原相对顺序）。"""
    ms = [str(m) for m in (p.get("sched_models") or [])]
    if not speed_first or len(ms) < 2:
        return ms
    try:
        from . import state as state_mod
    except Exception:
        return ms
    pid = str(p.get("id") or "")
    pos = {m: i for i, m in enumerate(ms)}

    def key(m: str):
        v = state_mod.speed_of(pid, m)
        return (0, v) if v else (1, pos.get(m, 999))

    try:
        return sorted(ms, key=key)
    except Exception:
        return ms


def select(cfg: dict, requested: str) -> Selection:
    req = (requested or "").strip()
    if not req:
        return Selection(False, 400, "缺少 model 字段")
    mode = cfg.get("mode", "smart")
    stars = _stars(cfg)
    speed_first = _speed_first_on(cfg)

    usable = []
    for p in (cfg.get("providers") or []):
        if not p.get("enabled", True):
            continue
        if mode == "safe" and not (p.get("trusted") or p.get("domestic")):
            continue
        usable.append(p)
    usable.sort(key=lambda p: (p.get("priority") or 99, p.get("name") or ""))

    cands: List[Candidate] = []
    starred: List[Candidate] = []

    def push(p: dict, m: str, idx: int) -> None:
        c = Candidate(p, m, idx)
        if f"{p.get('id')}::{m}" in stars:
            c.star = True
            starred.append(c)
        else:
            cands.append(c)

    # 虚拟模型 auto：按档位顺序遍历所有勾选的 (渠道, 模型)
    if req == "auto":
        for p in usable:
            for i, m in enumerate(_ordered_models(p, speed_first)):
                push(p, m, i + 1)
        if not cands and not starred:
            return Selection(False, 503, "还没有勾选任何调度模型：请在渠道页点击模型标签勾选")
        return Selection(True, 200, "", "auto", starred + cands)

    for p in usable:
        sched = _ordered_models(p, speed_first)
        if req in sched:
            push(p, req, sched.index(req) + 1)

    if not cands and not starred:
        if not usable:
            return Selection(False, 503, "没有启用中的渠道（安全路由下需启用标记为「可信」的渠道）")
        have = [p.get("name") for p in usable if req in (p.get("fetched_models") or [])]
        if have:
            return Selection(False, 404,
                             f"模型 “{req}” 存在于 {', '.join(have)}，但未勾选调度：请在渠道页点击该模型标签勾选")
        return Selection(False, 404, f"没有任何启用渠道提供模型 “{req}”")
    return Selection(True, 200, "", req, starred + cands)
