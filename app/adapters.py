"""上游协议适配：OpenAI 兼容（绝大多数服务）与 Anthropic 原生协议互转。"""
from __future__ import annotations

import json
import time
from typing import AsyncGenerator, List, Optional, Tuple

import httpx

ANTHROPIC_VERSION = "2023-06-01"
RETRYABLE_STATUS = {408, 429, 404, 500, 502, 503, 504, 529}

# 额度/配额耗尽类错误关键词（小写匹配）。命中即视为「渠道级故障」：
# 整个渠道进入渠道冷却池（长冷却），并立即切换到下一候选渠道。
QUOTA_PATTERNS = (
    "insufficient_quota", "quota exceeded", "quota_exceeded", "exceeded your current quota",
    "billing", "payment required", "余额不足", "额度不足", "额度已用完", "额度用尽",
    "额度已用尽", "用尽", "耗尽", "配额", "欠费", "充值", "过期", "已到期",
    "账户余额", "balance", "free quota", "免费额度",
)

def is_quota_error(status: int, message: str) -> bool:
    """额度类错误：渠道整体不可用（余额/配额/欠费/到期）。
    402 恒为额度类；403/401/429/500 等需消息命中关键词，避免误伤单模型问题。"""
    if status == 402:
        return True
    if status not in (401, 403, 429, 500):
        return False
    m = (message or "").lower()
    return any(k in m for k in QUOTA_PATTERNS)


def is_rate_limit_error(status: int, message: str) -> bool:
    """限流类错误（429 且非额度关键词）→ 渠道级短冷却：
    整个渠道繁忙，整渠道跳过一段时间，给上游喘息，避免各模型反复撞墙。"""
    if status != 429:
        return False
    return not is_quota_error(status, message)


# ---- 响应正文里的「额度耗尽通知」（假成功）识别 ----
# 部分上游（如电信云智助手/息壤等）不用错误状态码，而是返回 HTTP 200，
# 正文却是一段"+订购/购买 Token 套餐+"的额度耗尽通知。这类响应必须按额度类
# 处理（渠道长冷却），否则网关会一直往这个已经没额度的渠道发请求。
RESP_QUOTA_STRONG = (
    "额度已用完", "额度用尽", "额度耗尽", "额度不足", "token额度", "token 额度",
    "余额不足", "欠费", "insufficient_quota", "quota exceeded",
    "exceeded your current quota", "no quota", "配额已用完", "免费额度已用尽",
)
RESP_QUOTA_CONTEXT = (
    "购买", "订购", "充值", "套餐", "续费", "订购页面", "billing", "purchase",
    "subscribe", "http://", "https://",
)
# 正文过长（正常回答）不判定，避免用户聊到「额度已用完」被误判
RESP_QUOTA_MAX_LEN = 2500


def is_quota_text(text: str, max_len: int = RESP_QUOTA_MAX_LEN) -> bool:
    """判断「响应正文」是否是上游的额度耗尽通知（而非正常回答）。

    需同时满足：① 命中额度强关键词 ② 命中购买/订购/链接等上下文词
    ③ 正文足够短（系统通知通常很短）。三者同时命中才判定，降低误伤。
    """
    t = text or ""
    if not t or len(t) > max_len:
        return False
    low = t.lower()
    if not any(k.lower() in low for k in RESP_QUOTA_STRONG):
        return False
    return any(k.lower() in low for k in RESP_QUOTA_CONTEXT)


def text_of_openai_response(data) -> str:
    """从 OpenAI 格式响应里抽出正文（供额度通知检测用）。"""
    if not isinstance(data, dict):
        return ""
    ch = (data.get("choices") or [{}])
    ch0 = ch[0] if isinstance(ch, list) and ch else {}
    msg = (ch0.get("message") or {}) if isinstance(ch0, dict) else {}
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") in ("text", None))
    return ""


def text_of_openai_chunk(payload: str) -> str:
    """从一条 OpenAI 流式 chunk 载荷里抽出增量正文（也兼容 anthropic delta）。"""
    try:
        j = json.loads(payload)
    except Exception:
        return ""
    if not isinstance(j, dict):
        return ""
    ch = j.get("choices")
    if isinstance(ch, list) and ch:
        d = ch[0].get("delta") or {}
        c = d.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "".join(b.get("text", "") for b in c if isinstance(b, dict))
    d = j.get("delta") or {}
    if isinstance(d, dict):
        t = d.get("text") or d.get("thinking")
        if isinstance(t, str):
            return t
    c = j.get("content")
    if isinstance(c, str):
        return c
    return ""


class UpstreamError(Exception):
    """上游失败。retryable=True 时计入冷却池并尝试下一优先级。"""

    def __init__(self, message: str, status: int = 0, retryable: bool = True,
                 retry_after: Optional[float] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


def _base(p: dict) -> str:
    return (p.get("base_url") or "").strip().rstrip("/")


def provider_headers(p: dict) -> dict:
    if p.get("adapter") == "anthropic":
        return {
            "x-api-key": p.get("api_key") or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
    h = {"content-type": "application/json"}
    key = p.get("api_key") or ""
    if key:
        h["Authorization"] = "Bearer " + key
    return h


def chat_url(p: dict) -> str:
    b = _base(p)
    if p.get("adapter") == "anthropic":
        return b if b.endswith("/v1/messages") else b + "/v1/messages"
    return b + "/chat/completions"


def models_url(p: dict) -> str:
    b = _base(p)
    if p.get("adapter") == "anthropic":
        return b if b.endswith("/v1/models") else b + "/v1/models"
    return b + "/models"


def embeddings_url(p: dict) -> str:
    b = _base(p)
    if p.get("adapter") == "anthropic":
        raise UpstreamError("Anthropic 原生渠道不支持 embeddings", status=400, retryable=False)
    return b + "/embeddings"


def _err_msg(text: str) -> str:
    try:
        j = json.loads(text)
        if isinstance(j, dict):
            e = j.get("error") if isinstance(j.get("error"), (dict, str)) else j
            if isinstance(e, dict):
                return str(e.get("message") or e.get("msg") or text)[:300]
            return str(e)[:300]
    except Exception:
        pass
    return (text or "").strip()[:300] or "upstream error"


def raise_for_status(status: int, text: str, headers: Optional[httpx.Headers] = None) -> None:
    retry_after: Optional[float] = None
    if headers:
        try:
            retry_after = float(headers.get("retry-after") or 0) or None
        except Exception:
            retry_after = None
    raise UpstreamError(
        f"HTTP {status}: {_err_msg(text)}",
        status=status,
        retryable=status in RETRYABLE_STATUS or status >= 500,
        retry_after=retry_after,
    )


# ---------------------------------------------------------------- 请求构造

def _clean_empty_tool_calls(messages) -> list:
    """剔除 tool_calls 为空数组的字段：部分严格上游（DeepSeek 官方、支付宝百炼等）
    会因 "Empty tool_calls is not supported" 直接 400 拒绝整个请求。"""
    out = []
    for m in messages:
        if isinstance(m, dict) and isinstance(m.get("tool_calls"), list) and not m["tool_calls"]:
            m = {k: v for k, v in m.items() if k != "tool_calls"}
        out.append(m)
    return out


def build_payload(p: dict, body: dict, upstream_model: str) -> dict:
    if p.get("adapter") == "anthropic":
        return build_anthropic_payload(body, upstream_model, p)
    payload = dict(body)
    payload["model"] = upstream_model
    if isinstance(payload.get("messages"), list):
        payload["messages"] = _clean_empty_tool_calls(payload["messages"])
    _apply_thinking(payload, p, upstream_model)
    return payload


# ---- 思考强度统一化（不同厂商参数名不一致，这里归一） ----
# 统一值域：auto / off / low / medium / high / max（默认 max = 最高）
_THINK_LEVELS = ("auto", "off", "low", "medium", "high", "max")

# OpenAI 兼容：reasoning_effort 标准值（deepseek/qwen 等也用这套枚举）
_THINK_TO_EFFORT = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "high",      # OpenAI 无 max，用最接近的 high
    "auto": None,       # 不设置，交给上游默认
    "off": "none",      # 部分实现用 none 关闭；不支持的会被降级忽略
}

# Anthropic 原生：thinking 参数 + budget_tokens（按强度给预算）
_THINK_TO_BUDGET = {
    "low": 4096,
    "medium": 16384,
    "high": 32768,
    "max": 65536,
}


def _vendor_of(model: str) -> str:
    """按模型名粗判厂商，用于思考参数方言差异。"""
    m = (model or "").lower()
    if m.startswith(("claude", "anthropic")):
        return "anthropic"
    if m.startswith(("deepseek",)):
        return "deepseek"
    if m.startswith(("qw", "qwen")):
        return "qwen"
    if m.startswith(("glm", "zhipu", "chatglm")):
        return "glm"
    if m.startswith(("kimi", "moonshot")):
        return "kimi"
    if m.startswith(("gemini", "google")):
        return "gemini"
    if m.startswith(("gpt-5", "gpt-4", "o1", "o3", "o4")):
        return "openai"
    return "openai"  # 默认 OpenAI 兼容


# 推理/思考能力模型名特征（用于决定「默认最高」是否该注入参数；
# 不在名单里的模型一律不注入，避免给不支持的模型塞参数导致上游 400）
_REASONING_HINTS = (
    "thinking", "reasoner", "reasoning", "-r1", "qwq", "o1", "o3", "o4",
    "gpt-5", "gpt-oss", "qwen3", "glm-5", "glm-4.5", "glm-4.6", "glm-z1",
    "kimi-k3", "kimi-k2-thinking", "minimax-m3", "gemini-2.5", "gemini-3",
    "grok-3", "grok-4", "seed-oss", "hunyuan-think", "deepseek-v4", "deepseek-v3.1",
)


def _looks_reasoning(model: str) -> bool:
    m = (model or "").lower()
    return any(h in m for h in _REASONING_HINTS)


def _apply_thinking(payload: dict, p: dict, model: str) -> None:
    """把统一思考强度写进 OpenAI 兼容请求体（不同厂商思考参数名不一致，这里归一）。

    注入策略（保守，避免把不支持的模型搞 400）：
    - 渠道 model_thinking 里显式有该模型 或 "*" → 按用户/探测值注入
    - 否则：仅当模型名像推理模型（_looks_reasoning）时按默认 "max" 注入
    - 都不满足 → 不注入任何思考参数
    - level="auto" → 不注入（交给上游默认）
    """
    mt = (p.get("model_thinking") or {})
    explicit = mt.get(model)
    if explicit is None and "*" in mt:
        explicit = mt.get("*")
    if explicit is None and not _looks_reasoning(model):
        return  # 未知能力模型：安全起见不动它
    level = explicit or "max"
    level = level if level in _THINK_LEVELS else "max"

    if level == "auto":
        return  # 交给上游默认（不设参数）

    vendor = _vendor_of(model)

    effort = _THINK_TO_EFFORT.get(level)
    if effort is None:
        return
    # off 只在认识 thinking 的厂商里显式关，其它不管
    if level == "off" and vendor not in ("openai", "deepseek", "qwen", "glm", "kimi"):
        return

    if vendor in ("deepseek", "qwen", "glm", "kimi", "openai", "anthropic"):
        # 注意：本函数只服务 OpenAI 兼容路径（真 anthropic 原生渠道走 build_anthropic_payload），
        # 所以 claude 模型经中转站 OpenAI 接口调用时同样用 reasoning_effort。
        #
        # ⚠️ 这条路径上绝不要加 "thinking" 字段（v1.0.26~v1.0.29 的 bug，2026-10 修）：
        # thinking 是 Anthropic 专有方言，OpenAI 兼容上游会直接 400 拒绝——
        #   HTTP 400: "thinking" is not supported on /v1/chat/completions and was not applied.
        #             Use "reasoning_effort" (or "xxx.effort") to control thinking. (sharellm.net)
        # 旧代码在 qwen/deepseek 上额外塞 thinking={"type":"enabled","effort":...}，
        # 导致这两个厂商的模型每次请求白撞一次 400 再故障转移（迷你机实测 9 次，
        # zcode 侧表现为"网关工作不正常"）。统一强度只用 reasoning_effort：
        # openai/qwen/glm/kimi/deepseek 都认，off 档 → "none"。
        payload["reasoning_effort"] = effort
    else:
        # gemini 等：不强塞 reasoning_effort，交给上游
        pass


def _text_of(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for c in content if isinstance(content, list) else []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text") or "")
    return "\n".join(x for x in parts if x)


def _images_of(content) -> list:
    out = []
    if not isinstance(content, list):
        return out
    for c in content:
        if isinstance(c, dict) and c.get("type") == "image_url":
            url = ((c.get("image_url") or {}).get("url")) or ""
            if url.startswith("data:"):
                head, _, b64 = url.partition(",")
                mt = head[5:].split(";", 1)[0] or "image/png"
                out.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
    return out


def build_anthropic_payload(body: dict, model: str, p: dict | None = None) -> dict:
    sys_parts: List[str] = []
    msgs: List[dict] = []
    for m in body.get("messages") or []:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            t = _text_of(content)
            if t:
                sys_parts.append(t)
            continue
        if role == "tool":
            msgs.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or "",
                "content": _text_of(content) or "(empty)",
            }]})
            continue
        blocks = []
        t = _text_of(content)
        if t:
            blocks.append({"type": "text", "text": t})
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    inp = {}
                blocks.append({"type": "tool_use", "id": tc.get("id") or f"toolu_{len(blocks)}",
                               "name": fn.get("name") or "", "input": inp})
        else:
            blocks.extend(_images_of(content))
        if not blocks:
            blocks = [{"type": "text", "text": "(empty)"}]
        msgs.append({"role": "assistant" if role == "assistant" else "user", "content": blocks})

    merged: List[dict] = []
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] = merged[-1]["content"] + m["content"]
        else:
            merged.append(m)

    try:
        max_tokens = int(body.get("max_tokens") or 0)
    except Exception:
        max_tokens = 0
    out = {"model": model, "messages": merged, "max_tokens": max_tokens if max_tokens > 0 else 4096}
    if sys_parts:
        out["system"] = "\n\n".join(sys_parts)
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        out["top_p"] = body["top_p"]
    if body.get("stop"):
        s = body["stop"]
        out["stop_sequences"] = s if isinstance(s, list) else [s]
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        at = []
        for t in tools:
            if isinstance(t, dict) and isinstance(t.get("function"), dict):
                f = t["function"]
                at.append({"name": f.get("name") or "", "description": f.get("description") or "",
                           "input_schema": f.get("parameters") or {"type": "object", "properties": {}}})
        if at:
            out["tools"] = at
            tc = body.get("tool_choice")
            if isinstance(tc, str) and tc == "auto":
                out["tool_choice"] = {"type": "auto"}
            elif isinstance(tc, str) and tc == "required":
                out["tool_choice"] = {"type": "any"}
            elif isinstance(tc, dict) and tc.get("type") == "function":
                name = ((tc.get("function") or {}).get("name")) or ""
                if name:
                    out["tool_choice"] = {"type": "tool", "name": name}
    if body.get("stream"):
        out["stream"] = True
    _apply_anthropic_thinking(out, p, model)
    return out


def _apply_anthropic_thinking(out: dict, p: dict | None, model: str) -> None:
    """Anthropic 原生：thinking 模式支持统一思考强度。

    Anthropic 用 thinking {type, budget_tokens}；有 max 档但没有 effort 概念，
    以预算体现强度。Claude 无 thinking 档的模型（如某些）传 thinking 会 400，
    所以只在 claude 系模型名上注入，且 off 明确 type=disabled。
    """
    if not p or not (model or "").lower().startswith("claude"):
        return
    mt = p.get("model_thinking") or {}
    level = mt.get(model) or mt.get("*") or "max"
    level = level if level in _THINK_LEVELS else "max"
    if level == "auto":
        return  # 交给上游默认
    if level == "off":
        out["thinking"] = {"type": "disabled"}
        return
    budget = _THINK_TO_BUDGET.get(level, 16384)
    out["thinking"] = {"type": "enabled", "budget_tokens": budget}


# ---------------------------------------------------------------- 响应转换

_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
           "tool_use": "tool_calls", "refusal": "stop"}


def response_to_openai(p: dict, data: dict, requested_model: str) -> dict:
    if p.get("adapter") != "anthropic":
        return data
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    tcs = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            tcs.append({"id": b.get("id") or "toolu", "type": "function",
                        "function": {"name": b.get("name") or "",
                                     "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}})
    message = {"role": "assistant", "content": text if text else None}
    if tcs:
        message["tool_calls"] = tcs
    u = data.get("usage") or {}
    pt, ct = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
    return {
        "id": data.get("id") or f"chatcmpl-anthropic-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.get("model") or requested_model,
        "choices": [{"index": 0, "message": message,
                     "finish_reason": _FINISH.get(data.get("stop_reason") or "end_turn", "stop")}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
    }


# ---------------------------------------------------------------- 流式转换

def stream_chunks_openai(payload_str: str) -> Tuple[List[str], bool, Optional[str]]:
    """OpenAI 兼容：原样透传。返回 (chunks, done, error_json)。"""
    s = payload_str.strip()
    if not s:
        return ([], False, None)
    if s == "[DONE]":
        return (["data: [DONE]\n\n"], True, None)
    try:
        j = json.loads(s)
    except Exception:
        return ([f"data: {s}\n\n"], False, None)
    if isinstance(j, dict) and j.get("error"):
        return ([], False, json.dumps({"error": j["error"]}, ensure_ascii=False))
    return ([f"data: {s}\n\n"], False, None)


class AnthropicStreamState:
    def __init__(self, model: str):
        self.model = model
        self.cid = f"chatcmpl-anthropic-{int(time.time() * 1000)}"
        self.tool_i = 0
        self.stop = None
        self.usage_in = 0
        self.usage_out = 0


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _chunk(st: "AnthropicStreamState", delta: dict, finish=None, usage=None) -> str:
    d = {"id": st.cid, "object": "chat.completion.chunk", "created": int(time.time()),
         "model": st.model, "choices": [{"index": 0, "delta": delta}]}
    if finish is not None:
        d["choices"][0]["finish_reason"] = finish
    if usage is not None:
        d["usage"] = usage
    return _sse(d)


def stream_chunks_anthropic(st: "AnthropicStreamState", payload_str: str) -> Tuple[List[str], bool, Optional[str]]:
    try:
        ev = json.loads(payload_str)
    except Exception:
        return ([], False, None)
    if not isinstance(ev, dict):
        return ([], False, None)
    t = ev.get("type")
    chunks: List[str] = []
    if t == "error":
        e = ev.get("error") or {}
        msg = e.get("message") if isinstance(e, dict) else str(e)
        return ([], False, json.dumps({"error": {"message": msg or "upstream error",
                                                 "type": (e.get("type") if isinstance(e, dict) else None) or "upstream_error"}},
                                      ensure_ascii=False))
    if t == "message_start":
        u = ((ev.get("message") or {}).get("usage")) or {}
        st.usage_in = int(u.get("input_tokens", 0))
    elif t == "content_block_start":
        cb = ev.get("content_block") or {}
        if cb.get("type") == "tool_use":
            chunks.append(_chunk(st, {"tool_calls": [{
                "index": st.tool_i, "id": cb.get("id") or f"tool_{st.tool_i}", "type": "function",
                "function": {"name": cb.get("name") or "", "arguments": ""}}]}))
            st.tool_i += 1
    elif t == "content_block_delta":
        d = ev.get("delta") or {}
        dt = d.get("type")
        if dt == "text_delta":
            chunks.append(_chunk(st, {"content": d.get("text") or ""}))
        elif dt == "thinking_delta":
            chunks.append(_chunk(st, {"reasoning_content": d.get("thinking") or ""}))
        elif dt == "input_json_delta":
            chunks.append(_chunk(st, {"tool_calls": [{
                "index": max(0, st.tool_i - 1),
                "function": {"arguments": d.get("partial_json") or ""}}]}))
    elif t == "message_delta":
        d = ev.get("delta") or {}
        if d.get("stop_reason"):
            st.stop = _FINISH.get(d["stop_reason"], "stop")
        u = ev.get("usage") or {}
        if u.get("output_tokens"):
            st.usage_out = int(u["output_tokens"])
    elif t == "message_stop":
        chunks.append(_chunk(st, {}, finish=st.stop or "stop",
                             usage={"prompt_tokens": st.usage_in, "completion_tokens": st.usage_out,
                                    "total_tokens": st.usage_in + st.usage_out}))
        chunks.append("data: [DONE]\n\n")
        return (chunks, True, None)
    return (chunks, False, None)


async def iter_sse_data(resp: httpx.Response) -> AsyncGenerator[str, None]:
    """解析上游 SSE，产出每条 data 载荷（字符串，可能为 "[DONE]"）。"""
    buf = b""
    async for chunk in resp.aiter_bytes():
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.strip()
            if not line or line.startswith(b":"):
                continue
            if line.startswith(b"data:"):
                yield line[5:].strip().decode("utf-8", "replace")
    if buf:
        line = buf.strip()
        if line.startswith(b"data:"):
            yield line[5:].strip().decode("utf-8", "replace")


async def fetch_models(client: httpx.AsyncClient, p: dict):
    """返回 (模型ID列表, {模型: 上下文长度}, {模型: 思考能力标志})。
    部分上游 /models 会附带上下文元数据与思考能力字段。"""
    r = await client.get(models_url(p), headers=provider_headers(p), timeout=20)
    if r.status_code != 200:
        raise_for_status(r.status_code, r.text)
    try:
        j = r.json()
    except Exception:
        raise UpstreamError("模型列表不是合法 JSON", status=502)
    ids = []
    ctx = {}
    think = {}
    data = j.get("data") if isinstance(j, dict) else None
    if isinstance(data, list):
        for m in data:
            if not (isinstance(m, dict) and m.get("id")):
                continue
            mid = str(m["id"])
            ids.append(mid)
            for k in ("context_length", "max_model_len", "context_size", "max_context_length"):
                v = m.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    ctx[mid] = int(v)
                    break
            # 思考能力探测：上游显式标注字段更可信
            if _model_supports_thinking(m):
                think[mid] = True
    return sorted(set(ids)), ctx, think


def _model_supports_thinking(m: dict) -> bool:
    """判断上游 /models 里单个模型条目是否显示支持思考/推理模式。

    兼容不同厂商的字段名：OpenAI 用 reasoning_effort 存在/非null，
    部分中转用 thinking、enable_thinking、reasoning、reasoning_model，
    Anthropic 生态用 thinking_budget，(deepseek) 用 thinking 字段。
    """
    for k in ("reasoning_effort", "thinking", "enable_thinking", "reasoning",
              "reasoning_model", "thinking_budget", "enable_reasoning",
              "supports_thinking", "reasoning_effort_options"):
        v = m.get(k)
        if v is not None:
            # a value of False / "off" / 0 explicitly disables
            if isinstance(v, bool):
                return v
            if isinstance(v, str) and v.strip().lower() in ("false", "off", "none", "no", "0"):
                return False
            # list/float/other truthy presence = supported
            return True
    return False
