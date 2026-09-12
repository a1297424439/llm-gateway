# -*- coding: utf-8 -*-
"""L3 智能实体识别：自动发现文本里的人名/公司（机构）名，供脱密路由替换。

后端按可用性自动选择（均为可选依赖，装哪个用哪个，都装了优先准的）：
  1. LAC   —— 百度词法分析（pip install lac paddlepaddle），准确率更高
  2. jieba —— 随 requirements 内置（纯 Python），词性标注自带 nr/nt 标签

对外接口：
  backend_name()                 当前可用后端名（"lac"/"jieba"/"none"）
  extract_entities(text)         -> [(start, end, category)]
                                  category ∈ {"company", "person"}
地名不参与脱密（普通聊天里误报多、泄露价值低）。
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

# 超长字符串（工具输出等）做 NER 的开销上限：分块扫描，总量封顶
_CHUNK = 4000
_OVERLAP = 100
_MAX_CHARS = 40000

_backend_name: str = "none"
_extract_fn: Optional[Callable[[str], List[Tuple[int, int, str]]]] = None
_loaded = False


def _try_lac():
    global _extract_fn
    from LAC import LAC  # noqa: PLC0415（可选依赖，缺了走 jieba）

    model = LAC(mode="lac")
    cache: dict = {}

    def run(text: str) -> List[Tuple[int, int, str]]:
        out: List[Tuple[int, int, str]] = []
        for s, chunk in _chunks(text):
            r = cache.get(chunk)
            if r is None:
                words, tags = model.run(chunk)
                r = _merge(words, tags, {"ORG": "company", "PER": "person"})
                cache[chunk] = r
            for a, b, cat in r:
                out.append((a + s, b + s, cat))
        return out

    _extract_fn = run


def _try_jieba():
    global _extract_fn
    import logging

    import jieba
    import jieba.posseg as pseg  # noqa: PLC0415

    jieba.setLogLevel(logging.CRITICAL)

    def run(text: str) -> List[Tuple[int, int, str]]:
        out: List[Tuple[int, int, str]] = []
        for s, chunk in _chunks(text):
            toks = list(pseg.cut(chunk, HMM=True))
            tags = [w.flag for w in toks]
            words = [w.word for w in toks]
            # jieba 词性：nr* = 人名，nt* = 机构/公司名
            cat_of = lambda f: "person" if f.startswith("nr") else ("company" if f.startswith("nt") else "")
            r = _merge(words, tags, cat_of)
            for a, b, cat in r:
                out.append((a + s, b + s, cat))
        return out

    _extract_fn = run


def _chunks(text: str):
    """长文本按 _CHUNK 分块（带 _OVERLAP 防跨界实体截断），总量封顶。"""
    if len(text) <= _CHUNK:
        yield 0, text
        return
    pos, n = 0, min(len(text), _MAX_CHARS)
    while pos < n:
        end = min(pos + _CHUNK, n)
        yield pos, text[pos:end]
        if end >= n:
            break
        pos = end - _OVERLAP


def _merge(words: List[str], tags: List[str], cat_of) -> List[Tuple[int, int, str]]:
    """把相邻同类实体的 token 合并成一个 span；过短（单字）的丢弃降噪。"""
    spans: List[Tuple[int, int, str]] = []
    pos = 0
    for w, f in zip(words, tags):
        start, pos = pos, pos + len(w)
        cat = cat_of(f) if callable(cat_of) else cat_of.get(f, "")
        if not cat:
            continue
        if spans and spans[-1][2] == cat and spans[-1][1] == start:
            spans[-1] = (spans[-1][0], pos, cat)
        else:
            spans.append((start, pos, cat))
    return [(a, b, c) for a, b, c in spans if b - a >= 2]


def _ensure_loaded():
    global _loaded, _backend_name
    if _loaded:
        return
    _loaded = True
    for name, fn in (("lac", _try_lac), ("jieba", _try_jieba)):
        try:
            fn()
            _backend_name = name
            return
        except Exception:
            continue
    _backend_name = "none"


def backend_name() -> str:
    _ensure_loaded()
    return _backend_name


def extract_entities(text: str) -> List[Tuple[int, int, str]]:
    """返回文本中的实体 span。未启用/无后端时返回空。"""
    _ensure_loaded()
    if _extract_fn is None or not text:
        return []
    try:
        return _extract_fn(text)
    except Exception:
        return []


def set_backend_for_test(name: str, fn=None):
    """测试注入用。"""
    global _backend_name, _extract_fn, _loaded
    _loaded = True
    _backend_name = name
    _extract_fn = fn
