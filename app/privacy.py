# -*- coding: utf-8 -*-
"""脱密路由：三层敏感内容识别 + 可逆替换（占位符 ⇄ 回填）。

仅在路由模式 = mask「脱密路由」时生效：
- 可信渠道（trusted/domestic）按原文转发，不脱密；
- 普通（非可信）渠道：请求内容先脱密再转发；
- 上游响应（含流式 SSE、tool 参数）返回本机客户端前自动回填真实内容——
  真实值只回到本机，不出网。

三层识别（由确定到发现）：
  L1 正则规则 —— 密钥/令牌/证件号等。平台密钥模式节选自 gitleaks v8 默认规则库
     （config/gitleaks.toml）与 protectai/llm-guard Secrets 扫描器的公开规则，
     按聊天文本场景适配（去掉文件路径上下文约束、放宽长度）；PII 部分为
     Presidio 风格的通用规则（邮箱/手机号/身份证号[含校验位]/银行卡[Luhn]）。
  L2 敏感词库 —— 面板维护的公司/项目/人名等词目，绝对准确；占位符编号全局
     稳定（同一词条永远同一个占位符，多轮对话跨请求一致）。
  L3 智能识别 —— 可选 NER 后端自动发现未录入词库的人名/公司名（见 ner.py）。

占位符：[SEC-n]（L1）、[公司n]/[项目n]/[人名n]/[地名n]/[敏感n]（L2/L3）。
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import ner as ner_mod

CATEGORY_LABELS = {"company": "公司", "project": "项目", "person": "人名",
                   "place": "地名", "custom": "敏感"}
RULE_KEYS = ["api_keys", "key_value_pairs", "emails", "phones", "id_cards",
             "uscc", "private_keys", "bank_cards"]
# 各规则组默认开关（用户配置缺省时生效；bank_cards 误伤面大默认关）
_RULE_DEFAULTS = {"bank_cards": False}
_NER_MAX_CHARS = 40000  # 单个字符串参与 NER 的长度上限（L1/L2 不受限）

# ---------------------------------------------------------------- L1 规则
# (组名, 正则列表, 编译flags, 校验器)。密钥类规则源头：gitleaks / llm-guard。
def _cn_id_ok(s: str) -> bool:
    """GB 11643 校验位（mod 11-2）。"""
    if len(s) != 18:
        return False
    w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    try:
        total = sum(int(s[i]) * w[i] for i in range(17))
    except ValueError:
        return False
    return "10X98765432"[total % 11] == s[17].upper()


def _luhn_ok(s: str) -> bool:
    total, alt = 0, False
    for ch in reversed(s):
        d = ord(ch) - 48
        if d < 0 or d > 9:
            return False
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _uscc_ok(s: str) -> bool:
    """统一社会信用代码校验位（ISO 7064 MOD 31-3）。"""
    chars = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    wi = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]
    try:
        total = sum(chars.index(s[i].upper()) * wi[i] for i in range(17))
    except ValueError:
        return False
    return chars[(31 - total % 31) % 31] == s[17].upper()


_L1: List[Tuple[str, List[str], int, Optional[Callable[[str], bool]]]] = [
    ("private_keys", [
        # gitleaks: private-key
        r"-----BEGIN[ A-Z0-9_-]{0,64}PRIVATE KEY(?: BLOCK)?-----.{64,}?-----END[ A-Z0-9_-]{0,64}PRIVATE KEY(?: BLOCK)?-----",
    ], re.S | re.I, None),
    ("api_keys", [
        # OpenAI/Anthropic/DeepSeek/Moonshot 等 sk- 系（gitleaks openai/generic 简化）
        r"\bsk-[A-Za-z0-9_-]{16,}\b",
        # JWT（gitleaks: jwt）
        r"\bey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b",
        # AWS（gitleaks: aws-access-token）
        r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b",
        # Google（gitleaks: gcp-api-key）
        r"\bAIza[0-9A-Za-z_\-]{35}\b",
        # GitHub（gitleaks: github-pat / github-fine-grained-pat，长度放宽）
        r"\bgh[pousr]_[0-9A-Za-z]{36}\b",
        r"\bgithub_pat_[0-9A-Za-z_]{22,}\b",
        # GitLab（gitleaks: gitlab-pat）
        r"\bglpat-[0-9A-Za-z_\-]{20,}\b",
        # Stripe（gitleaks: stripe-access-token）
        r"\b(?:sk|rk)_(?:test|live|prod)_[A-Za-z0-9]{10,}\b",
        # Slack（gitleaks: slack-token / slack app 级 / webhook）
        r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b",
        r"\bxapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+",
        r"hooks\.slack\.com/services/[A-Za-z0-9+/]{40,}",
        # Telegram bot（gitleaks: telegram-bot-api-token 简化）
        r"\b\d{5,16}:AA[0-9A-Za-z_\-]{32,34}\b",
        # SendGrid（gitleaks: sendgrid-api-token）
        r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b",
        # npm（gitleaks: npm-access-token）
        r"\bnpm_[A-Za-z0-9]{36}\b",
        # PyPI（gitleaks: pypi-upload-token）
        r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}\b",
        # HuggingFace（gitleaks: huggingface-access-token）
        r"\bhf_[A-Za-z0-9]{34}\b",
        # DigitalOcean（gitleaks: digitalocean-access-token）
        r"\bd[oop]_v1_[a-f0-9]{64}\b",
        # Shopify（gitleaks: shopify-*）
        r"\bshp(?:at|ca|pa|ss)_[a-fA-F0-9]{32}\b",
        # Twilio（gitleaks: twilio-api-key）
        r"\bSK[0-9a-fA-F]{32}\b",
        # URL 内嵌凭据 user:pass@host（llm-guard 风格）
        r"\bhttps?://[^\s/@:]+:[^\s/@]{8,}@[^\s]+",
        # Bearer 头（llm-guard Secrets）
        r"\bBearer\s+[A-Za-z0-9._+/=\-]{16,}",
    ], 0, None),
    ("key_value_pairs", [
        # gitleaks generic-api-key 的简化版：按赋值上下文抓密钥值（无熵过滤，宁多勿漏）
        r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|secret|password|passwd|pwd)\b"
        r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-+/=.]{8,}",
    ], 0, None),
    ("emails", [
        r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
    ], 0, None),
    ("phones", [
        # 中国大陆手机号（Presidio 风格 + 边界约束）
        r"(?<!\d)1[3-9]\d{9}(?!\d)",
        # 座机（区号-号码 格式，如 0771-1234567）
        r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)",
    ], 0, None),
    ("id_cards", [
        # 18 位身份证号（含校验位验证降噪）
        r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)",
    ], 0, _cn_id_ok),
    ("uscc", [
        # 统一社会信用代码（18 位，含 ISO 7064 MOD 31-3 校验位验证）
        r"(?<![0-9A-HJ-NPQRTUWXY])[159Y][1239Y6ME][0-9A-HJ-NPQRTUWXY]{16}(?![0-9A-HJ-NPQRTUWXY])",
    ], 0, _uscc_ok),
    ("bank_cards", [
        # 13~19 位卡号（Luhn 校验；默认关闭）
        r"(?<!\d)[3-6]\d{12,18}(?!\d)",
    ], 0, _luhn_ok),
]

# L2/L3 占位符编号（进程级稳定：同一词条/实体在任何请求里都是同一编号）
_STABLE_SEQ: Dict[Tuple[str, str], int] = {}
_CAT_SEQ: Dict[str, int] = {}
_STABLE_CAP = 5000


def _stable_placeholder(cat: str, secret: str) -> str:
    key = (cat, secret)
    n = _STABLE_SEQ.get(key)
    if n is None:
        if len(_STABLE_SEQ) >= _STABLE_CAP:
            _STABLE_SEQ.clear()
            _CAT_SEQ.clear()
        n = _CAT_SEQ.get(cat, 0) + 1
        _CAT_SEQ[cat] = n
        _STABLE_SEQ[key] = n
    return "[" + CATEGORY_LABELS.get(cat, "敏感") + str(n) + "]"


class MaskSession:
    """单次请求的脱密会话。L1 用会话内编号 [SEC-n]；L2/L3 用全局稳定编号。"""

    def __init__(self, patterns, glossary, ner_enabled):
        self.patterns = patterns            # [(compiled, validator)]
        self.glossary = glossary            # [(compiled, category)]
        self.ner_enabled = ner_enabled
        self.mapping: Dict[Tuple[str, str], str] = {}   # (cat, secret) -> placeholder
        self._restore: Optional[Dict[str, str]] = None
        self._sec_n = 0

    def useful(self) -> bool:
        return bool(self.mapping)

    # -- 请求方向 ---------------------------------------------------------
    def mask_text(self, text: str) -> str:
        if not text:
            return text
        spans: List[Tuple[int, int, int, str]] = []
        for pat, cat in self.glossary:                    # L2：词库（最高优先）
            for m in pat.finditer(text):
                spans.append((m.start(), m.end(), 0, cat))
        for pat, validator in self.patterns:              # L1：正则
            for m in pat.finditer(text):
                if validator and not validator(m.group(0)):
                    continue
                spans.append((m.start(), m.end(), 1, "SEC"))
        if self.ner_enabled and len(text) <= _NER_MAX_CHARS:   # L3：NER
            for s, e, cat in ner_mod.extract_entities(text):
                spans.append((s, e, 2, cat))
        if not spans:
            return text
        # 重叠择优：起点靠前 > 匹配更长 > 层级更高（词库>正则>NER）
        spans.sort(key=lambda x: (x[0], -(x[1] - x[0]), x[2]))
        out, pos, last_end = [], 0, -1
        for s, e, _, cat in spans:
            if s < last_end:
                continue
            secret = text[s:e]
            key = (cat, secret)
            ph = self.mapping.get(key)
            if ph is None:
                ph = ("[SEC-%d]" % (self._sec_n + 1)) if cat == "SEC" \
                    else _stable_placeholder(cat, secret)
                if cat == "SEC":
                    self._sec_n += 1
                self.mapping[key] = ph
                self._restore = None
            out.append(text[pos:s])
            out.append(ph)
            pos = last_end = e
        out.append(text[pos:])
        return "".join(out)

    # -- 响应方向 ---------------------------------------------------------
    def restore_text(self, text: str) -> str:
        if not text or not self.mapping:
            return text
        if self._restore is None:
            self._restore = {ph: sec for (_, sec), ph in self.mapping.items()}
        for ph, sec in self._restore.items():
            if ph in text:
                text = text.replace(ph, sec)
        return text

    def walk(self, obj: Any, fn: Callable[[str], str]) -> Any:
        """递归遍历 dict/list，对所有字符串值应用 fn（原地）。"""
        if isinstance(obj, str):
            return fn(obj)
        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = self.walk(v, fn)
            return obj
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                obj[i] = self.walk(v, fn)
            return obj
        return obj

    def placeholders(self):
        return {ph for ph in self.mapping.values()}

    def mask_obj(self, obj: Any) -> Any:
        return self.walk(obj, self.mask_text)

    def restore_obj(self, obj: Any) -> Any:
        if not self.mapping:
            return obj
        return self.walk(obj, self.restore_text)


def make_session(cfg: dict) -> Optional[MaskSession]:
    """脱密路由模式下构建会话；其他模式返回 None（调用方零开销直通）。"""
    if (cfg or {}).get("mode") != "mask":
        return None
    pv = (cfg or {}).get("privacy") or {}
    rules = pv.get("rules") or {}
    patterns = []
    for group, regexes, flags, validator in _L1:
        if not rules.get(group, _RULE_DEFAULTS.get(group, True)):
            continue
        for r in regexes:
            try:
                patterns.append((re.compile(r, flags), validator))
            except re.error:
                continue
    glossary = []
    for item in pv.get("glossary") or []:
        term = str((item or {}).get("term") or "").strip()
        if not term:
            continue
        cat = item.get("category") if item.get("category") in CATEGORY_LABELS else "custom"
        esc = re.escape(term)
        if term.isascii():
            esc = r"(?<![A-Za-z0-9])" + esc + r"(?![A-Za-z0-9])"
        try:
            glossary.append((re.compile(esc, re.I if term.isascii() else 0), cat))
        except re.error:
            continue
    # 自定义正则/字面词（extra_words）：re: 前缀 = 正则，否则按字面词处理
    for w in pv.get("extra_words") or []:
        w = str(w or "").strip()
        if not w:
            continue
        try:
            if w.lower().startswith("re:"):
                glossary.append((re.compile(w[3:]), "custom"))
            else:
                glossary.append((re.compile(re.escape(w)), "custom"))
        except re.error:
            continue
    return MaskSession(patterns, glossary, bool(pv.get("ner_entities")))


def should_mask(provider: dict) -> bool:
    """可信渠道（trusted/domestic）原文转发；其余脱密。"""
    p = provider or {}
    return not (p.get("trusted") or p.get("domestic"))


def mask_body(ms: Optional[MaskSession], body: dict) -> dict:
    """返回脱密后的请求体深拷贝（不动原 body，可信渠道继续用原文）。"""
    if ms is None:
        return body
    return ms.mask_obj(copy.deepcopy(body))


def restore_out(ms: Optional[MaskSession], out: Any) -> Any:
    """响应回填：占位符还原为真实内容（只在返回本机的路上做）。"""
    if ms is None or not ms.useful():
        return out
    return ms.restore_obj(out)


def restore_sse(ms: Optional[MaskSession], payload_str: str) -> str:
    """还原单条 SSE data 载荷（完整 JSON 行，占位符不会被网络分包截断）。"""
    if ms is None or not ms.useful():
        return payload_str
    try:
        ev = json.loads(payload_str)
    except Exception:
        return payload_str
    if not isinstance(ev, (dict, list)):
        return payload_str
    return json.dumps(ms.restore_obj(ev), ensure_ascii=False)


class StreamRestorer:
    """跨 SSE 事件的流式回填。

    占位符可能被上游按 token 切进相邻两个事件（如 "[SEC-" + "1]"），单事件内
    还原会漏。按 JSON 路径给每个字符串字段挂起"未闭合的占位符前缀"，拼到同
    路径的下一个事件里再还原——上游增量事件同字段路径稳定，两条协议都覆盖。
    """

    def __init__(self, ms: Optional[MaskSession]):
        self.ms = ms
        self._pending: Dict[str, str] = {}
        self._phs = ms.placeholders() if (ms and ms.useful()) else set()

    def feed(self, payload_str: str) -> str:
        """处理一条 SSE data 载荷，返回还原后的载荷字符串。"""
        if not self._phs:
            return payload_str
        try:
            ev = json.loads(payload_str)
        except Exception:
            return payload_str
        if not isinstance(ev, (dict, list)):
            return payload_str
        held, self._pending = self._pending, {}
        ev = self._walk(ev, "", held)
        return json.dumps(ev, ensure_ascii=False)

    def _walk(self, node: Any, path: str, held: Dict[str, str]) -> Any:
        if isinstance(node, dict):
            return {k: self._walk(v, path + "/" + str(k), held) for k, v in node.items()}
        if isinstance(node, list):
            return [self._walk(v, path + "/" + str(i), held) for i, v in enumerate(node)]
        if isinstance(node, str):
            s = held.pop(path, "") + node
            s = self.ms.restore_text(s)
            tail = self._open_tail(s)
            if tail:
                s = s[: -len(tail)]
                self._pending[path] = tail
            return s
        return node

    def _open_tail(self, s: str) -> str:
        """若 s 以某个已知占位符的真前缀（未闭合的 '[' 片段）结尾，返回该片段。"""
        i = s.rfind("[")
        if i == -1:
            return ""
        frag = s[i:]
        if "]" in frag:
            return ""
        for ph in self._phs:
            if ph != frag and ph.startswith(frag):
                return frag
        return ""


def ner_name() -> str:
    """当前 L3 可用后端（none=需 pip install jieba 或 lac）。"""
    try:
        return ner_mod.backend_name()
    except Exception:
        return "none"
