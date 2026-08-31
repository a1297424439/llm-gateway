"""Anthropic Messages 协议兼容层：
- Anthropic 请求 → OpenAI Chat 请求（system / 图片 / 工具 / 工具结果）
- OpenAI 响应 → Anthropic 响应（text / tool_use / thinking / usage / stop_reason）
- OpenAI 流式 chunk → Anthropic SSE 事件（message_start / content_block_* / message_delta / message_stop）
"""

from __future__ import annotations

import json
import uuid


def _now_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def to_openai_request(body: dict) -> dict:
    """Anthropic Messages 请求体 → OpenAI Chat Completions 请求体。"""
    out: dict = {"model": body.get("model") or "auto"}

    system = body.get("system")
    if isinstance(system, list):
        system = "\n".join(b.get("text", "") for b in system
                           if isinstance(b, dict) and b.get("type") == "text")
    msgs: list = []
    if system:
        msgs.append({"role": "system", "content": system})

    for m in body.get("messages") or []:
        role = m.get("role")
        content = m.get("content")

        if role == "assistant":
            blocks = content if isinstance(content, list) else (
                [{"type": "text", "text": content}] if content else [])
            texts, tool_calls = [], []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text" and b.get("text"):
                    texts.append(b["text"])
                elif t == "tool_use":
                    tool_calls.append({"id": b.get("id") or _now_id("toolu"), "type": "function",
                                       "function": {"name": b.get("name") or "",
                                                    "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}})
            msg = {"role": "assistant", "content": "\n".join(texts) if texts else None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            if msg["content"] is None and not tool_calls:
                msg["content"] = ""
            msgs.append(msg)
            continue

        blocks = content if isinstance(content, list) else (
            [{"type": "text", "text": str(content)}] if content else [])
        parts, tool_results = [], []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and b.get("text"):
                parts.append({"type": "text", "text": b["text"]})
            elif t == "image":
                src = b.get("source") or {}
                if src.get("type") == "base64":
                    parts.append({"type": "image_url",
                                  "image_url": {"url": f'data:{src.get("media_type", "image/png")};base64,{src.get("data", "")}'}})
            elif t == "tool_result":
                inner = b.get("content")
                if isinstance(inner, list):
                    inner = "\n".join(x.get("text", "") for x in inner
                                      if isinstance(x, dict) and x.get("type") == "text")
                tool_results.append({"role": "tool", "tool_use_id": b.get("tool_use_id") or "",
                                     "content": inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)})
        if tool_results:
            msgs.extend(tool_results)
            if parts:
                msgs.append({"role": "user", "content": parts})
        else:
            msgs.append({"role": "user", "content": parts if parts else (content or "")})

    out["messages"] = msgs
    if body.get("max_tokens"):
        out["max_tokens"] = int(body.get("max_tokens") or 0) or None
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        out["top_p"] = body["top_p"]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]

    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        ot = []
        for t in tools:
            if isinstance(t, dict) and t.get("name"):
                ot.append({"type": "function",
                           "function": {"name": t["name"], "description": t.get("description") or "",
                                        "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}})
        if ot:
            out["tools"] = ot
            tc = body.get("tool_choice")
            if isinstance(tc, dict):
                tt = tc.get("type")
                if tt == "auto":
                    out["tool_choice"] = "auto"
                elif tt == "any":
                    out["tool_choice"] = "required"
                elif tt == "tool" and tc.get("name"):
                    out["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}
    if body.get("stream"):
        out["stream"] = True
    return out


_STOP_MAP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use",
             "content_filter": "refusal", None: None}


def openai_to_anthropic(data: dict, model: str) -> dict:
    ch = (data.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content: list = []
    rc = msg.get("reasoning_content")
    if rc:
        content.append({"type": "thinking", "thinking": rc, "signature": ""})
    c = msg.get("content")
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                content.append({"type": "text", "text": b["text"]})
    elif c:
        content.append({"type": "text", "text": c})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            inp = json.loads(fn.get("arguments") or "{}")
        except Exception:
            inp = {}
        content.append({"type": "tool_use", "id": tc.get("id") or _now_id("toolu"),
                        "name": fn.get("name") or "", "input": inp})
    if not content:
        content = [{"type": "text", "text": ""}]
    u = data.get("usage") or {}
    fr = ch.get("finish_reason")
    return {
        "id": data.get("id") or _now_id("msg"),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": _STOP_MAP.get(fr, "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": u.get("prompt_tokens", 0),
                  "output_tokens": u.get("completion_tokens", 0)},
    }


def anthropic_error(status: int, message: str, etype: str = "invalid_request_error") -> dict:
    return {"type": "error", "error": {"type": etype, "message": message}}


class StreamToAnthropic:
    """OpenAI 流式 chunk dict → Anthropic SSE 事件串（增量 feed）。"""

    def __init__(self, model: str):
        self.model = model
        self.mid = _now_id("msg")
        self.started = False
        self.finished = False
        self.blocks = []      # 已打开的内容块 [{idx, kind, tool_id?, openai_idx?}]
        self.next_idx = 0
        self.tool_ids = {}    # openai 工具下标 -> anthropic tool id
        self.stop_reason = None
        self.usage_in = 0
        self.usage_out = 0

    def _ev(self, event: str, data: dict) -> str:
        return f"event: {event}\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"

    def _open_block(self, kind: str, tool_id=None, tool_name=None):
        """打开（或复用）内容块，返回 (index, content_block_start 事件)。"""
        if kind in ("text", "thinking"):
            for b in self.blocks:
                if b["kind"] == kind:
                    return b["idx"], None
        idx = self.next_idx
        self.next_idx += 1
        b = {"idx": idx, "kind": kind}
        if kind == "tool":
            tid = tool_id or _now_id("toolu")
            b["tool_id"] = tid
            b["tool_name"] = tool_name or ""
        self.blocks.append(b)
        cb = {"type": kind}
        if kind == "tool":
            cb = {"type": "tool_use", "id": b["tool_id"], "name": b["tool_name"], "input": {}}
        start = self._ev("content_block_start", {"type": "content_block_start", "index": idx, "content_block": cb})
        return idx, start

    def feed(self, chunk: dict) -> list:
        """输入一个 OpenAI chunk dict，返回要下发的 SSE 事件列表。"""
        evs: list = []
        if self.finished:
            return evs
        if not self.started:
            self.started = True
            evs.append(self._ev("message_start", {
                "type": "message_start",
                "message": {"id": self.mid, "type": "message", "role": "assistant",
                            "model": self.model, "content": [],
                            "usage": {"input_tokens": 0, "output_tokens": 0}}}))

        u = chunk.get("usage")
        if u:
            self.usage_in = u.get("prompt_tokens", self.usage_in)
            self.usage_out = u.get("completion_tokens", self.usage_out)

        choices = chunk.get("choices") or []
        ch = choices[0] if choices else {}
        delta = ch.get("delta") or {}

        if delta.get("reasoning_content"):
            idx, start = self._open_block("thinking")
            if start:
                evs.append(start)
            evs.append(self._ev("content_block_delta", {
                "type": "content_block_delta", "index": idx,
                "delta": {"type": "thinking_delta", "thinking": delta["reasoning_content"]}}))

        if delta.get("content"):
            idx, start = self._open_block("text")
            if start:
                evs.append(start)
            evs.append(self._ev("content_block_delta", {
                "type": "content_block_delta", "index": idx,
                "delta": {"type": "text_delta", "text": delta["content"]}}))

        for tc in delta.get("tool_calls") or []:
            ti = tc.get("index", 0)
            if ti not in self.tool_ids:
                self.tool_ids[ti] = _now_id("toolu")
                fn_name = ((tc.get("function") or {}).get("name")) or ""
                idx, start = self._open_block("tool", tool_id=self.tool_ids[ti], tool_name=fn_name)
                evs.append(start)
            args = (tc.get("function") or {}).get("arguments")
            if args:
                tidx = next(b["idx"] for b in self.blocks
                            if b["kind"] == "tool" and b.get("openai_idx") == ti)
                evs.append(self._ev("content_block_delta", {
                    "type": "content_block_delta", "index": tidx,
                    "delta": {"type": "input_json_delta", "partial_json": args}}))

        fr = ch.get("finish_reason")
        if fr:
            self.stop_reason = _STOP_MAP.get(fr, "end_turn")
        return evs

    def finish(self) -> list:
        """上游结束时调用：闭合所有内容块并下发 message_delta / message_stop。"""
        evs: list = []
        for b in sorted(self.blocks, key=lambda x: x["idx"]):
            evs.append(self._ev("content_block_stop", {"type": "content_block_stop", "index": b["idx"]}))
        evs.append(self._ev("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": self.stop_reason or "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": self.usage_out or 0}}))
        evs.append(self._ev("message_stop", {"type": "message_stop"}))
        self.finished = True
        return evs
