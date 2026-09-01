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
        return build_anthropic_payload(body, upstream_model)
    payload = dict(body)
    payload["model"] = upstream_model
    if isinstance(payload.get("messages"), list):
        payload["messages"] = _clean_empty_tool_calls(payload["messages"])
    return payload


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


def build_anthropic_payload(body: dict, model: str) -> dict:
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
    return out


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
    """返回 (模型ID列表, {模型: 上下文长度})。部分上游 /models 会附带上下文元数据。"""
    r = await client.get(models_url(p), headers=provider_headers(p), timeout=20)
    if r.status_code != 200:
        raise_for_status(r.status_code, r.text)
    try:
        j = r.json()
    except Exception:
        raise UpstreamError("模型列表不是合法 JSON", status=502)
    ids = []
    ctx = {}
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
    return sorted(set(ids)), ctx
