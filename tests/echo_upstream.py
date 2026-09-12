"""脱密测试用回声上游（OpenAI 兼容）：把收到的最后一条 user 消息原样回在回复里，
并支持 GET /received 检查网关实际发来了什么——用于断言「上游看到的是脱密后的内容」。

    python tests/echo_upstream.py 9311
"""
import json
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
LAST = {"body": None}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "mock-chat", "object": "model"}]}


@app.get("/received")
async def received():
    return {"last_body": LAST["body"]}


def _last_user_text(body: dict) -> str:
    for m in reversed(body.get("messages") or []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return ""


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    LAST["body"] = body
    content = _last_user_text(body)
    if body.get("stream"):
        async def gen():
            # 按 7 字符分片：保证占位符大概率被切开，验证流式跨事件回填
            for i in range(0, len(content), 7):
                piece = content[i:i + 7]
                yield "data: " + json.dumps(
                    {"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps(
                {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return JSONResponse({
        "id": "echo", "object": "chat.completion", "created": 0, "model": body.get("model"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ECHO:" + content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
