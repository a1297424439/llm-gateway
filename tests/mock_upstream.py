"""本地 Mock 上游（OpenAI 兼容），用于自测与体验：
    python tests/mock_upstream.py 9301 ok     # 正常返回
    python tests/mock_upstream.py 9302 fail   # 始终返回 500
"""
import asyncio
import json
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODE = "ok"
TAG = "mock"

app = FastAPI()


@app.get("/health")
async def health():
    return {"ok": True, "mode": MODE}


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [
        {"id": "mock-chat", "object": "model"},
        {"id": "mock-embed", "object": "model"},
    ]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    if MODE == "fail":
        return JSONResponse(status_code=500, content={"error": {"message": f"mock upstream failure ({TAG})"}})
    model = body.get("model") or "mock"
    if body.get("stream"):
        async def gen():
            for t in ["你好，", "来自 ", TAG]:
                yield "data: " + json.dumps({
                    "id": "cmpl-mock", "object": "chat.completion.chunk", "model": model,
                    "choices": [{"index": 0, "delta": {"content": t}}],
                }, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(0.02)
            yield "data: " + json.dumps({
                "id": "cmpl-mock", "object": "chat.completion.chunk", "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }) + "\n\ndata: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {
        "id": "cmpl-mock", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": f"hello from {TAG} for {model}"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 5, "total_tokens": 7},
    }


@app.post("/v1/embeddings")
async def embed(req: Request):
    body = await req.json()
    if MODE == "fail":
        return JSONResponse(status_code=500, content={"error": {"message": "mock failure"}})
    n = len(str(body.get("input") or ""))
    return {"object": "list", "model": body.get("model"), "data": [
        {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
        "usage": {"prompt_tokens": n, "total_tokens": n}}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9301
    if len(sys.argv) > 2:
        MODE = sys.argv[2]
    TAG = f"mock-{port}"
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
