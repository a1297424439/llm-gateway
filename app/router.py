"""智能路由调度：按渠道档位（优先级）在勾选的 (渠道, 模型) 组合间调度。

不再有别名/映射：客户端直接请求上游模型名，凡是被勾选参与调度的渠道都会
按 档位优先级 依次尝试；失败进冷却池，自动落到下一个渠道。同名模型在多个
渠道被勾选时即天然互备。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Candidate:
    provider: dict
    model: str
    entry_priority: int = 1

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


def select(cfg: dict, requested: str) -> Selection:
    req = (requested or "").strip()
    if not req:
        return Selection(False, 400, "缺少 model 字段")
    mode = cfg.get("mode", "smart")

    usable = []
    for p in (cfg.get("providers") or []):
        if not p.get("enabled", True):
            continue
        if mode == "safe" and not (p.get("trusted") or p.get("domestic")):
            continue
        usable.append(p)
    usable.sort(key=lambda p: (p.get("priority") or 99, p.get("name") or ""))

    cands: List[Candidate] = []

    # 虚拟模型 auto：按档位顺序遍历所有勾选的 (渠道, 模型)
    if req == "auto":
        for p in usable:
            for i, m in enumerate(p.get("sched_models") or []):
                cands.append(Candidate(p, m, i + 1))
        if not cands:
            return Selection(False, 503, "还没有勾选任何调度模型：请在渠道页点击模型标签勾选")
        return Selection(True, 200, "", "auto", cands)
    for p in usable:
        sched = p.get("sched_models") or []
        if req in sched:
            cands.append(Candidate(p, req, sched.index(req) + 1))

    if not cands:
        if not usable:
            return Selection(False, 503, "没有启用中的渠道（安全路由下需启用标记为「可信」的渠道）")
        have = [p.get("name") for p in usable if req in (p.get("fetched_models") or [])]
        if have:
            return Selection(False, 404,
                             f"模型 “{req}” 存在于 {', '.join(have)}，但未勾选调度：请在渠道页点击该模型标签勾选")
        return Selection(False, 404, f"没有任何启用渠道提供模型 “{req}”")
    return Selection(True, 200, "", req, cands)
