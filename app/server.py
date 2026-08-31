"""FastAPI 应用：

- /v1/*        OpenAI 兼容网关（chat/completions、embeddings、models），失败转移 + 冷却池

- /api/*       管理面板接口（本机免鉴权，非本机需携带网关 Key）

- /            iOS 风格管理面板（web/ 静态资源）

"""

from __future__ import annotations



import asyncio

import copy

import hmac

import json

import os

import re

import secrets

import socket

import subprocess

import sys

import threading

import time

from contextlib import asynccontextmanager

from pathlib import Path



import httpx

from fastapi import Depends, FastAPI, Request

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from fastapi.staticfiles import StaticFiles

from starlette.exceptions import HTTPException as StarletteHTTPException



from . import VERSION, adapters, config as cfgmod, presets as preset_mod, router as router_mod

from . import state as state_mod



CLIENT: httpx.AsyncClient | None = None



window_ref = None   # 由 main 注入（窗口模式）

srv_ref = None

tray_ref = None

START_TS = time.time()

STARTUP_PORT: int | None = None

STARTUP_HOST: str | None = None

_last_restart = 0.0





def _web_dir() -> Path:

    if getattr(sys, "frozen", False):

        return Path(getattr(sys, "_MEIPASS", ".")) / "web"

    return Path(__file__).resolve().parent.parent / "web"





async def _probe_provider(pid: str):

    """拉取渠道模型列表并识别上下文（超时短、失败静默记录，不打扰）。"""

    cfg = cfgmod.cfg()

    p = _find_provider(cfg, pid)

    if not p:

        return

    t0 = time.time()

    try:

        models, ctxmap = await adapters.fetch_models(CLIENT, p)



        def mut(c: dict):

            pp = _find_provider(c, pid)

            if not pp:

                return

            pp["fetched_models"] = models

            pp.setdefault("model_context", {})

            for k, v in ctxmap.items():

                pp["model_context"].setdefault(k, v)

            pp["last_test"] = {"ok": True, "ts": time.time(), "detail": f"连接正常，{len(models)} 个模型"}

        cfgmod.mutate(mut)

        state_mod.log_request(ok=True, ms=int((time.time() - t0) * 1000), stream=False,

                              alias="模型列表", provider=p.get("name"),

                              model=f"自动识别（{len(models)} 个模型）")

    except Exception as e:

        detail = str(e)[:300]



        def mut(c: dict):

            pp = _find_provider(c, pid)

            if pp:

                pp["last_test"] = {"ok": False, "ts": time.time(), "detail": detail}

        cfgmod.mutate(mut)

        state_mod.log_request(ok=False, ms=int((time.time() - t0) * 1000), stream=False,

                              alias="模型列表", provider=p.get("name"),

                              model="自动识别失败", error=detail)





async def _slow_probe_loop():

    """启动后慢速补测：从未测试/失败的渠道里每次只挑一个，间隔 25 秒；

    失败渠道每 10 分钟才会被重试一次，绝不集中轰炸。"""

    await asyncio.sleep(15)

    while True:

        try:

            cfg = cfgmod.cfg()

            now = time.time()

            cand = None

            for p in cfg.get("providers") or []:

                lt = p.get("last_test") or {}

                if not lt.get("ok"):

                    if not lt or now - float(lt.get("ts") or 0) > 3600:   # 一小时一次

                        cand = p["id"]

                        break

            if cand:

                await _probe_provider(cand)

                await asyncio.sleep(25)

                continue

        except Exception:

            pass

        await asyncio.sleep(60)





@asynccontextmanager

async def lifespan(app: FastAPI):

    global CLIENT, STARTUP_PORT, STARTUP_HOST

    CLIENT = httpx.AsyncClient(limits=httpx.Limits(max_connections=128, max_keepalive_connections=32))

    state_mod.load()

    cfg = cfgmod.load()

    STARTUP_PORT = int(cfg["server"].get("port") or 0)

    STARTUP_HOST = cfg["server"].get("host") or "127.0.0.1"

    task = asyncio.create_task(_persist_loop())

    probe = asyncio.create_task(_slow_probe_loop())

    try:

        yield

    finally:

        task.cancel()

        probe.cancel()

        state_mod.persist()

        await CLIENT.aclose()





async def _persist_loop():

    while True:

        await asyncio.sleep(5)

        state_mod.maybe_persist()





app = FastAPI(title="LLM Gateway", version=VERSION, lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],

                   allow_headers=["*"], allow_credentials=False)





@app.exception_handler(StarletteHTTPException)

async def _http_exc(req: Request, exc: StarletteHTTPException):

    return JSONResponse(status_code=exc.status_code,

                        content={"error": {"message": str(exc.detail), "type": "gateway_error"}})





@app.exception_handler(Exception)

async def _generic_exc(req: Request, exc: Exception):

    return JSONResponse(status_code=500,

                        content={"error": {"message": f"网关内部错误: {exc}", "type": "internal_error"}})





# ---------------------------------------------------------------- 鉴权



def _extract_key(req: Request) -> str:

    h = req.headers.get("authorization") or ""

    if h.lower().startswith("bearer "):

        return h[7:].strip()

    return (req.headers.get("x-api-key") or req.query_params.get("key") or "").strip()





def _is_loopback(req: Request) -> bool:

    try:

        return req.client.host in ("127.0.0.1", "::1", "localhost")

    except Exception:

        return False





async def gateway_auth(req: Request):

    key = _extract_key(req)

    real = cfgmod.cfg()["server"].get("key") or ""

    if not key or not real or not hmac.compare_digest(key, real):

        raise StarletteHTTPException(401, "无效的 API Key（网关本地密钥不匹配）")





async def api_auth(req: Request):

    if _is_loopback(req):

        return

    key = _extract_key(req)

    real = cfgmod.cfg()["server"].get("key") or ""

    if not key or not real or not hmac.compare_digest(key, real):

        raise StarletteHTTPException(401, "未授权：请先在面板输入访问密钥")





def _gw_error(status: int, message: str, extra=None) -> JSONResponse:

    content = {"error": {"message": message, "type": "gateway_error"}}

    if extra:

        content["error"]["details"] = extra

    return JSONResponse(status_code=status, content=content)





def lan_ip() -> str:

    try:

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        s.settimeout(0.5)

        s.connect(("223.5.5.5", 53))

        ip = s.getsockname()[0]

        s.close()

        return ip

    except Exception:

        return "127.0.0.1"





# ---------------------------------------------------------------- 网关 /v1



def _timeout(cfg: dict) -> httpx.Timeout:

    t = 120

    try:

        t = int(cfg["routing"].get("timeout_seconds") or 120)

    except Exception:

        pass

    return httpx.Timeout(connect=15, read=max(10, t), write=60, pool=10)





@app.get("/health")

async def health():

    return {"ok": True, "version": VERSION, "uptime": int(time.time() - START_TS)}





@app.get("/v1/models")

async def v1_models(_=Depends(gateway_auth)):

    """可调度模型并集 + 虚拟模型 auto（按档位调度）。

    每个模型带 context_length（同名字段，供智能体识别上下文；auto 取勾选模型的最小值）。"""

    cfg = cfgmod.cfg()

    mode = cfg.get("mode")

    serving = {}

    for p in cfg.get("providers") or []:

        if not p.get("enabled", True):

            continue

        if mode == "safe" and not (p.get("trusted") or p.get("domestic")):

            continue

        for m in p.get("sched_models") or []:

            c = resolve_ctx(p, m)[0]

            cur = serving.get(m)

            if c and (cur is None or c < cur):

                serving[m] = c

            elif m not in serving:

                serving[m] = 0

    entries = [{"id": "auto", "object": "model", "created": int(START_TS),

                "owned_by": "llm-gateway",

                "context_length": min([c for c in serving.values() if c]) if serving else None}]

    for n in sorted(serving):

        entries.append({"id": n, "object": "model", "created": int(START_TS),

                        "owned_by": "llm-gateway", "context_length": serving[n] or None})

    return {"object": "list", "data": entries}





@app.post("/v1/chat/completions")

async def chat_completions(req: Request, _=Depends(gateway_auth)):

    try:

        body = await req.json()

    except Exception:

        return _gw_error(400, "请求体不是合法 JSON")

    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):

        return _gw_error(400, "缺少 messages 字段")

    cfg = cfgmod.cfg()

    sel = router_mod.select(cfg, str(body.get("model") or ""))

    if not sel.ok:

        return _gw_error(sel.code, sel.message)

    return await _execute(cfg, sel, body, stream=bool(body.get("stream")))





from . import anthropic_compat


def _anth_error(status: int, message: str):
    return JSONResponse(status_code=status,
                        content=anthropic_compat.anthropic_error(status, message))


@app.post("/v1/messages")
async def v1_messages(req: Request, _=Depends(gateway_auth)):
    """Anthropic Messages 协议兼容端点（/v1/messages），供 Claude 方言客户端使用。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse(status_code=400,
                            content=anthropic_compat.anthropic_error(400, "请求体不是合法 JSON"))
    model = str(body.get("model") or "auto")
    stream = bool(body.get("stream"))
    cfg = cfgmod.cfg()
    sel = router_mod.select(cfg, model)
    if not sel.ok:
        return JSONResponse(status_code=sel.code,
                            content=anthropic_compat.anthropic_error(sel.code, sel.message))
    body_openai = anthropic_compat.to_openai_request(body)
    routing = cfg.get("routing") or {}
    try:
        max_attempts = max(1, int(routing.get("max_attempts") or 4))
    except Exception:
        max_attempts = 4
    cooldown_cfg = cfg.get("cooldown") or {}
    base = max(1, int(cooldown_cfg.get("base_seconds") or 60))
    maxs = max(base, int(cooldown_cfg.get("max_seconds") or 1800))

    attempts_log = []
    tried = 0
    last_provider = None
    skip_providers = set()
    t_start = time.time()
    last_err = ""

    for cand in sel.candidates:
        if tried >= max_attempts:
            break
        if cand.provider["id"] in skip_providers:
            continue
        blocked, remain = state_mod.blocked(cand.key)
        if blocked:
            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,
                                 "skipped": "冷却中，剩余 " + str(int(remain)) + " 秒"})
            continue
        pblocked, prem = state_mod.provider_blocked(cand.provider["id"])
        if pblocked:
            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,
                                 "skipped": f"渠道冷却中（额度），剩余 {int(prem)} 秒"})
            continue
        # max_attempts 按「渠道」计数：同一渠道内的模型连续失败不消耗次数，
        # 保证渠道内全部勾选模型试完才降级到下一渠道（site_first 语义）。
        if cand.provider["id"] != last_provider:
            tried += 1
            last_provider = cand.provider["id"]
        t0 = time.time()
        payload = dict(body_openai)
        payload["model"] = cand.model
        payload["stream"] = stream
        hreq = CLIENT.build_request("POST", adapters.chat_url(cand.provider),
                                    headers=adapters.provider_headers(cand.provider),
                                    json=payload, timeout=_timeout(cfg))
        try:
            r = await CLIENT.send(hreq)
            if r.status_code != 200:
                adapters.raise_for_status(r.status_code, r.text, r.headers)
            if stream:
                conv = anthropic_compat.StreamToAnthropic(str(body.get("model") or cand.model))
                state_mod.mark_success(cand.key)
                state_mod.provider_mark_success(cand.provider["id"])
                state_mod.log_request(ok=True, ms=int((time.time() - t0) * 1000), stream=True,
                                      alias=sel.alias, provider=cand.provider.get("name"),
                                      model=cand.model, attempts=attempts_log)
                NL = chr(10)

                async def gen():
                    try:
                        buf = ""
                        async for raw in r.aiter_bytes():
                            buf += raw.decode("utf-8", "replace")
                            while NL in buf:
                                ln, buf = buf.split(NL, 1)
                                ln = ln.strip()
                                if not ln.startswith("data:"):
                                    continue
                                data = ln[5:].strip()
                                if data == "[DONE]":
                                    break
                                try:
                                    evs = conv.feed(json.loads(data))
                                except Exception:
                                    continue
                                for e in evs:
                                    yield e
                        for e in conv.finish():
                            yield e
                    except Exception:
                        pass
                    finally:
                        await r.aclose()

                return StreamingResponse(gen(), media_type="text/event-stream",
                                         headers={"Cache-Control": "no-cache",
                                                  "X-Accel-Buffering": "no"})
            data = r.json()
            out = anthropic_compat.openai_to_anthropic(data, str(body.get("model") or cand.model))
            state_mod.mark_success(cand.key)
            state_mod.provider_mark_success(cand.provider["id"])
            state_mod.log_request(ok=True, ms=int((time.time() - t0) * 1000), stream=False,
                                  alias=sel.alias, provider=cand.provider.get("name"),
                                  model=cand.model,
                                  usage=(data.get("usage") or {}).get("prompt_tokens"),
                                  attempts=attempts_log)
            return JSONResponse(out)
        except adapters.UpstreamError as e:
            if adapters.is_quota_error(e.status, str(e)):
                state_mod.mark_provider_fail(cand.provider["id"], str(e), "quota")
                skip_providers.add(cand.provider["id"])
            elif adapters.is_rate_limit_error(e.status, str(e)):
                state_mod.mark_provider_fail(cand.provider["id"], str(e), "rate")
                skip_providers.add(cand.provider["id"])
            elif e.retryable:
                state_mod.mark_fail(cand.key, base, maxs, e.retry_after, str(e))
            if e.status in (401, 403):
                skip_providers.add(cand.provider["id"])
            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,
                                 "status": e.status or "network", "error": str(e)[:200],
                                 "cooldown": bool(e.retryable)})
            last_err = str(e)[:200]
        except httpx.HTTPError as e:
            state_mod.mark_fail(cand.key, base, maxs, None, str(e))
            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,
                                 "status": "network", "error": str(e)[:200], "cooldown": True})
            last_err = str(e)[:200]

    state_mod.log_request(ok=False, ms=int((time.time() - t_start) * 1000), stream=stream,
                          alias=sel.alias, provider=None, model=str(body.get("model") or ""),
                          error="所有候选渠道均失败", attempts=attempts_log)
    return JSONResponse(status_code=502,
                        content=anthropic_compat.anthropic_error(502, "所有候选渠道均失败（已按档位依次尝试）：" + last_err))



@app.post("/v1/embeddings")

async def embeddings(req: Request, _=Depends(gateway_auth)):

    try:

        body = await req.json()

    except Exception:

        return _gw_error(400, "请求体不是合法 JSON")

    cfg = cfgmod.cfg()

    sel = router_mod.select(cfg, str(body.get("model") or ""))

    if not sel.ok:

        return _gw_error(sel.code, sel.message)

    sel.candidates = [c for c in sel.candidates if c.provider.get("adapter") != "anthropic"]

    if not sel.candidates:

        return _gw_error(503, "embeddings 仅支持 OpenAI 兼容渠道")

    return await _execute(cfg, sel, body, stream=False, endpoint="embeddings")





async def _execute(cfg: dict, sel, body: dict, stream: bool, endpoint: str = "chat"):

    routing = cfg["routing"]

    try:

        max_attempts = max(1, int(routing.get("max_attempts") or 4))

    except Exception:

        max_attempts = 4

    base = max(1, int(cfg["cooldown"].get("base_seconds") or 60))

    maxs = max(base, int(cfg["cooldown"].get("max_seconds") or 1800))



    attempts_log = []

    tried = 0

    last_provider = None

    skip_providers = set()

    t_start = time.time()



    for cand in sel.candidates:

        if tried >= max_attempts:

            break

        if cand.provider["id"] in skip_providers:

            continue

        blocked, remain = state_mod.blocked(cand.key)

        if blocked:

            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,

                                 "skipped": f"冷却中，剩余 {int(remain)} 秒"})

            continue

        pblocked, prem = state_mod.provider_blocked(cand.provider["id"])

        if pblocked:

            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,

                                 "skipped": f"渠道冷却中（额度），剩余 {int(prem)} 秒"})

            continue

        # max_attempts 按「渠道」计数：同一渠道内的模型连续失败不消耗次数，
        # 保证渠道内全部勾选模型试完才降级到下一渠道（site_first 语义）。
        if cand.provider["id"] != last_provider:

            tried += 1

            last_provider = cand.provider["id"]

        t0 = time.time()

        usage_box = {}

        try:

            if stream:

                resp = await _attempt_stream(cfg, cand, body)

            else:

                resp = await _attempt_json(cfg, cand, body, endpoint, usage_box)

            state_mod.mark_success(cand.key)

            state_mod.provider_mark_success(cand.provider["id"])

            state_mod.log_request(ok=True, ms=int((time.time() - t0) * 1000), stream=stream,

                                  alias=sel.alias, provider=cand.provider.get("name"),

                                  model=cand.model, attempts=attempts_log,

                                  usage=usage_box or None)

            return resp

        except adapters.UpstreamError as e:

            if adapters.is_quota_error(e.status, str(e)):

                state_mod.mark_provider_fail(cand.provider["id"], str(e), "quota")

                skip_providers.add(cand.provider["id"])

            elif adapters.is_rate_limit_error(e.status, str(e)):

                state_mod.mark_provider_fail(cand.provider["id"], str(e), "rate")

                skip_providers.add(cand.provider["id"])

            elif e.retryable:

                state_mod.mark_fail(cand.key, base, maxs, e.retry_after, str(e))

            if e.status in (401, 403):

                skip_providers.add(cand.provider["id"])

            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,

                                 "status": e.status or "network", "error": str(e)[:200],

                                 "cooldown": bool(e.retryable)})

        except httpx.HTTPError as e:

            state_mod.mark_fail(cand.key, base, maxs, None, str(e))

            attempts_log.append({"provider": cand.provider.get("name"), "model": cand.model,

                                 "status": "network", "error": str(e)[:200], "cooldown": True})



    state_mod.log_request(ok=False, ms=int((time.time() - t_start) * 1000), stream=stream,

                          alias=sel.alias, provider=None, model=str(body.get("model") or ""),

                          error="所有候选渠道均失败", attempts=attempts_log)

    msg = "所有候选渠道均失败（按优先级依次尝试，失败渠道已进入冷却池）"

    return _gw_error(502, msg, extra=attempts_log)





async def _attempt_json(cfg: dict, cand, body: dict, endpoint: str = "chat", usage_box: dict | None = None):

    p = cand.provider

    payload = adapters.build_payload(p, body, cand.model)

    url = adapters.chat_url(p) if endpoint == "chat" else adapters.embeddings_url(p)

    hreq = CLIENT.build_request("POST", url, headers=adapters.provider_headers(p),

                                json=payload, timeout=_timeout(cfg))

    r = await CLIENT.send(hreq)

    try:

        if r.status_code != 200:

            adapters.raise_for_status(r.status_code, r.text, r.headers)

        try:

            data = r.json()

        except Exception:

            raise adapters.UpstreamError("上游返回非 JSON 响应", status=502)

        if isinstance(data, dict):

            if data.get("error"):

                raise adapters.UpstreamError("上游错误: " + json.dumps(data["error"], ensure_ascii=False)[:300],

                                             status=502)

            if p.get("adapter") == "anthropic" and data.get("type") == "error":

                e = data.get("error") or {}

                raise adapters.UpstreamError("上游错误: " + str(e.get("message") if isinstance(e, dict) else e),

                                             status=502)

    finally:

        try:

            await r.aclose()

        except Exception:

            pass

    if endpoint == "chat":

        out = adapters.response_to_openai(p, data, str(body.get("model") or cand.model))

        if usage_box is not None and isinstance(out, dict):

            u = out.get("usage") or {}

            usage_box.update({"p": u.get("prompt_tokens"), "c": u.get("completion_tokens")})

    else:

        out = data

    return JSONResponse(out)





async def _attempt_stream(cfg: dict, cand, body: dict):

    p = cand.provider

    payload = adapters.build_payload(p, body, cand.model)

    hreq = CLIENT.build_request("POST", adapters.chat_url(p), headers=adapters.provider_headers(p),

                                json=payload, timeout=_timeout(cfg))

    r = await CLIENT.send(hreq, stream=True)

    try:

        if r.status_code != 200:

            text = (await r.aread()).decode("utf-8", "replace")

            await r.aclose()

            adapters.raise_for_status(r.status_code, text, r.headers)



        agen = adapters.iter_sse_data(r)

        try:

            first = await agen.__anext__()

        except StopAsyncIteration:

            await r.aclose()

            raise adapters.UpstreamError("上游返回了空流", status=502)

        except httpx.HTTPError as e:

            await r.aclose()

            raise adapters.UpstreamError(f"流读取失败: {e}", status=0)



        if p.get("adapter") == "anthropic":

            st = adapters.AnthropicStreamState(cand.model)

            chunks, done, err = adapters.stream_chunks_anthropic(st, first)

        else:

            st = None

            chunks, done, err = adapters.stream_chunks_openai(first)

        if err:

            await r.aclose()

            raise adapters.UpstreamError("上游流错误: " + err[:300], status=502)



        state_mod.mark_success(cand.key)



        async def gen():

            try:

                for c in (chunks or []):

                    yield c

                if done:

                    return

                async for pl in agen:

                    if p.get("adapter") == "anthropic":

                        ch, dd, er = adapters.stream_chunks_anthropic(st, pl)

                    else:

                        ch, dd, er = adapters.stream_chunks_openai(pl)

                    if er:

                        yield "data: " + er + "\n\n"

                        yield "data: [DONE]\n\n"

                        return

                    for c in ch:

                        yield c

                    if dd:

                        return

                yield "data: [DONE]\n\n"

            except httpx.HTTPError as e:

                msg = json.dumps({"error": {"message": f"流中断: {e}", "type": "upstream_error"}},

                                 ensure_ascii=False)

                yield "data: " + msg + "\n\n"

                yield "data: [DONE]\n\n"

            finally:

                try:

                    await r.aclose()

                except Exception:

                    pass



        return StreamingResponse(gen(), media_type="text/event-stream",

                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    except Exception:

        try:

            await r.aclose()

        except Exception:

            pass

        raise





# ---------------------------------------------------------------- 管理面板 /api



def _server_info(cfg: dict) -> dict:

    port = cfg["server"].get("port")

    host = cfg["server"].get("host") or "127.0.0.1"

    urls = [{"label": "本机", "url": f"http://127.0.0.1:{port}/v1"}]

    lan = None

    if host == "0.0.0.0":

        lan = lan_ip()

        urls.append({"label": "局域网", "url": f"http://{lan}:{port}/v1"})

    return {"urls": urls, "lan_ip": lan}





@app.get("/api/state")

async def api_state(_=Depends(api_auth)):

    cfg = cfgmod.load()

    c = copy.deepcopy(cfg)

    pending = bool(c.pop("_pending_restart", False))

    for p in c.get("providers") or []:

        mc = {}

        for m in p.get("fetched_models") or []:

            ctx, exact = resolve_ctx(p, m)

            if ctx:

                mc[m] = [ctx, exact]

        p["model_ctx"] = mc

    info = _server_info(cfg)

    return {

        "config": c,

        "urls": info["urls"],

        "lan_ip": info["lan_ip"],

        "uptime": int(time.time() - START_TS),

        "version": VERSION,

        "pending_restart": pending,

        "config_path": str(cfgmod.config_path()),

        "cooldowns": state_mod.snapshot(cfg.get("providers") or []),

        "stats": state_mod.stats(),

        "logs": list(state_mod.LOGS)[-300:][::-1],

    }





@app.get("/api/presets")

async def api_presets(_=Depends(api_auth)):

    return {"presets": preset_mod.PRESETS}





def _sanitize_section(dst: dict, patch: dict, keys, cast=None):

    for k in keys:

        if k in patch:

            v = patch[k]

            if cast:

                try:

                    v = cast(v)

                except Exception:

                    continue

            dst[k] = v





@app.post("/api/settings")

async def api_settings(req: Request, _=Depends(api_auth)):

    body = await req.json()

    if not isinstance(body, dict):

        raise StarletteHTTPException(400, "请求体必须是 JSON 对象")



    def mut(cfg: dict):

        if body.get("mode") in ("smart", "safe"):

            cfg["mode"] = body["mode"]

        r = body.get("routing")

        if isinstance(r, dict):

            dst = cfg["routing"]

            if r.get("strategy") in ("site_first", "model_first"):

                dst["strategy"] = r["strategy"]

            _sanitize_section(dst, r, ["max_attempts", "timeout_seconds"], int)

            if isinstance(r.get("whitelist"), list):

                dst["whitelist"] = [str(x) for x in r["whitelist"] if str(x).strip()]

            for k in ("whitelist_enabled", "whitelist_fallback"):

                if k in r:

                    dst[k] = bool(r[k])

        c = body.get("cooldown")

        if isinstance(c, dict):

            _sanitize_section(cfg["cooldown"], c, ["base_seconds", "max_seconds"], int)

        s = body.get("server")

        if isinstance(s, dict):

            if s.get("host") in ("127.0.0.1", "0.0.0.0") and cfg["server"].get("host") != s["host"]:

                cfg["server"]["host"] = s["host"]

                cfg["_pending_restart"] = True

            if "lan_allowed" in s:

                cfg["server"]["lan_allowed"] = bool(s["lan_allowed"])

            if s.get("close_action") in ("", "quit", "hide"):

                cfg["server"]["close_action"] = s["close_action"]

        if isinstance(body.get("recommended_model"), str):

            cfg["recommended_model"] = body["recommended_model"].strip()[:100]



    cfgmod.mutate(mut)

    return {"ok": True}





@app.post("/api/server/regenerate-key")

async def api_regenerate_key(_=Depends(api_auth)):

    def mut(cfg: dict):

        hist = cfg["server"].setdefault("key_history", [])

        cfg["server"]["key"] = cfgmod.new_key(hist)

        hist.append(cfg["server"]["key"])

        if len(hist) > 50:

            del hist[:-50]

        return cfg["server"]["key"]

    key = cfgmod.mutate(mut)

    return {"ok": True, "key": key}





@app.post("/api/server/regenerate-port")

async def api_regenerate_port(_=Depends(api_auth)):

    def mut(cfg: dict):

        cfg["server"]["port"] = cfgmod.random_free_port(cfg["server"].get("host") or "127.0.0.1")

        cfg["_pending_restart"] = True

        return cfg["server"]["port"]

    port = cfgmod.mutate(mut)

    return {"ok": True, "port": port}



@app.post("/api/server/set-port")

async def api_set_port(req: Request, _=Depends(api_auth)):

    """手动指定监听端口，保存后需重启生效。"""

    body = await req.json()

    port = body.get("port")

    if not isinstance(port, int) or port < 1 or port > 65535:

        raise StarletteHTTPException(400, "端口必须在 1–65535 之间")

    def mut(cfg: dict):

        cfg["server"]["port"] = port

        cfg["_pending_restart"] = True

    cfgmod.mutate(mut)

    return {"ok": True, "port": port}





@app.post("/api/server/restart")

async def api_restart(_=Depends(api_auth)):

    global _last_restart

    if time.time() - _last_restart < 5:

        return {"ok": False, "error": "请勿频繁重启"}

    _last_restart = time.time()



    def _do():

        time.sleep(0.8)

        extra = list(sys.argv[1:])   # 保留 --no-ui / --browser 等启动参数

        if getattr(sys, "frozen", False):

            args = [sys.executable] + extra

        else:

            script = os.path.abspath(sys.argv[0])

            args = [sys.executable, script] + extra

        cwd = os.path.dirname(script) if not getattr(sys, "frozen", False) else None

        try:

            subprocess.Popen(args, cwd=cwd)

        except Exception:

            return

        os._exit(0)



    threading.Thread(target=_do, daemon=True).start()

    return {"ok": True}





# ---- 渠道 ----



def _find_provider(cfg: dict, pid: str):

    for p in cfg.get("providers") or []:

        if p.get("id") == pid:

            return p

    return None





@app.post("/api/providers")

async def provider_create(req: Request, _=Depends(api_auth)):

    b = await req.json()

    name = str(b.get("name") or "").strip()

    base_url = str(b.get("base_url") or "").strip()

    if not name or not base_url.startswith("http"):

        raise StarletteHTTPException(400, "名称与 Base URL 必填，URL 需以 http(s) 开头")

    adapter = b.get("adapter") if b.get("adapter") in ("openai", "anthropic") else "openai"

    pid = "p_" + secrets.token_hex(4)



    def mut(cfg: dict):

        prio = max([int(p.get("priority") or 1) for p in cfg["providers"]] or [0]) + 1

        cfg["providers"].append({

            "id": pid, "name": name, "base_url": base_url,

            "api_key": str(b.get("api_key") or ""), "adapter": adapter,

            "trusted": bool(b.get("trusted", b.get("domestic"))), "enabled": bool(b.get("enabled", True)),

            "priority": prio, "note": str(b.get("note") or ""),

            "fetched_models": [], "sched_models": [], "last_test": None,

        })

    cfgmod.mutate(mut)

    asyncio.create_task(_probe_provider(pid))

    return {"ok": True, "id": pid}





@app.put("/api/providers/{pid}")

async def provider_update(pid: str, req: Request, _=Depends(api_auth)):

    b = await req.json()



    def mut(cfg: dict):

        p = _find_provider(cfg, pid)

        if not p:

            raise StarletteHTTPException(404, "渠道不存在")

        for k in ("name", "base_url", "api_key", "note"):

            if k in b:

                p[k] = str(b[k] or "")

        if b.get("adapter") in ("openai", "anthropic"):

            p["adapter"] = b["adapter"]

        if "domestic" in b and "trusted" not in b:  # 兼容旧前端字段
            b["trusted"] = b["domestic"]
        for k in ("trusted", "enabled"):

            if k in b:

                p[k] = bool(b[k])

        if isinstance(b.get("sched_models"), list):

            p["sched_models"] = [str(x).strip() for x in b["sched_models"] if str(x).strip()]

        if isinstance(b.get("model_context"), dict):

            p["model_context"] = {str(k): [int(v[0]), bool(v[1])] for k, v in b["model_context"].items() if isinstance(v, (list, tuple)) and len(v) >= 2}

        if "priority" in b:

            try:

                p["priority"] = max(1, int(b["priority"]))

            except Exception:

                pass

    cfgmod.mutate(mut)

    return {"ok": True}





@app.delete("/api/providers/{pid}")

async def provider_delete(pid: str, _=Depends(api_auth)):

    def mut(cfg: dict):

        cfg["providers"] = [p for p in cfg["providers"] if p.get("id") != pid]

        for a in cfg.get("aliases") or []:

            a["mappings"] = [m for m in (a.get("mappings") or []) if m.get("provider_id") != pid]

    cfgmod.mutate(mut)

    state_mod.clear_provider(pid)

    return {"ok": True}





@app.post("/api/providers/{pid}/models-add")

async def provider_model_add(pid: str, req: Request, _=Depends(api_auth)):

    """手动添加模型名到渠道（不请求上游）。"""

    b = await req.json()

    model = str(b.get("model") or "").strip()

    if not model:

        raise StarletteHTTPException(400, "模型名不能为空")



    def mut(cfg: dict):

        p = _find_provider(cfg, pid)

        if not p:

            raise StarletteHTTPException(404, "渠道不存在")

        fm = p.setdefault("fetched_models", [])

        if model not in fm:

            fm.append(model)

    cfgmod.mutate(mut)

    return {"ok": True}





@app.post("/api/providers/{pid}/refresh")

async def provider_refresh(pid: str, _=Depends(api_auth)):

    cfg = cfgmod.cfg()

    p = _find_provider(cfg, pid)

    if not p:

        raise StarletteHTTPException(404, "渠道不存在")

    t0 = time.time()

    try:

        models, ctxmap = await adapters.fetch_models(CLIENT, p)



        def mut(c: dict):

            pp = _find_provider(c, pid)

            if pp:

                pp["fetched_models"] = models

                pp.setdefault("model_context", {})

                for k, v in ctxmap.items():

                    pp["model_context"].setdefault(k, v)

                pp["last_test"] = {"ok": True, "ts": time.time(), "detail": f"连接正常，{len(models)} 个模型"}

        cfgmod.mutate(mut)

        state_mod.log_request(ok=True, ms=int((time.time() - t0) * 1000), stream=False,

                              alias="模型列表", provider=p.get("name"),

                              model=f"手动刷新（{len(models)} 个模型）")

        return {"ok": True, "models": models}

    except Exception as e:

        detail = str(e)[:300]



        def mut(c: dict):

            pp = _find_provider(c, pid)

            if pp:

                pp["last_test"] = {"ok": False, "ts": time.time(), "detail": detail}

        cfgmod.mutate(mut)

        state_mod.log_request(ok=False, ms=int((time.time() - t0) * 1000), stream=False,

                              alias="模型列表", provider=p.get("name"),

                              model="手动刷新失败", error=detail)

        return {"ok": False, "error": detail}





# ---- 上下文识别：渠道自带元数据优先，缺了按模型家族规则推测 ----

_CTX_PATTERNS = [

    (r"^deepseek", 1000000),

    (r"^kimi-k3", 1024000),

    (r"^kimi-k2", 262144),

    (r"^glm-5\.1", 204800),

    (r"^glm-5", 1024000),

    (r"^glm-4", 131072),

    (r"^qwen3\.[0-9]+-max", 1000000),

    (r"^qwen3\.[0-9]+", 262144),

    (r"^minimax-m3", 1000000),

    (r"^minimax", 204800),

    (r"^claude-opus", 1000000),

    (r"^claude", 200000),

    (r"^grok-4", 500000),

    (r"^seed-2", 262144),

    (r"^mimo", 262144),

    (r"^step-3", 262144),

    (r"^longcat", 1024000),

    (r"^gemini-2", 1000000),

    (r"^gpt-5", 400000),

    (r"^gpt-4o", 128000),

    (r"^gpt-4", 8192),

    (r"^o[1-4]", 200000),

]





def _guess_ctx(name: str) -> int:

    for pat, ctx in _CTX_PATTERNS:

        if re.match(pat, name.strip(), re.IGNORECASE):

            return ctx

    return 0





def resolve_ctx(p: dict, model: str):

    """返回 (上下文长度, 是否精确)。渠道标注优先，其次家族规则推测。未知返回 (0, False)。"""

    v = (p.get("model_context") or {}).get(model)

    if v:

        try:

            return int(v), True

        except Exception:

            pass

    g = _guess_ctx(model)

    return (g, False) if g else (0, False)



@app.post("/api/providers/reorder")

async def providers_reorder(req: Request, _=Depends(api_auth)):

    """拖拽排序：前端把卡片拖好后提交三个档位的渠道 ID 顺序，

    服务端按 档位基数(1/10/20)+位置 重新分配优先级。最上面最优先。"""

    b = await req.json()

    tiers = b.get("tiers")

    if not isinstance(tiers, list) or len(tiers) != 3:

        raise StarletteHTTPException(400, "tiers 必须是 3 个数组")



    def mut(cfg: dict):

        by_id = {p.get("id"): p for p in cfg.get("providers") or []}

        bases = (1, 10, 20)

        for ti, ids in enumerate(tiers):

            if not isinstance(ids, list):

                raise StarletteHTTPException(400, "tiers 元素必须是数组")

            for i, pid in enumerate(ids):

                p = by_id.get(pid)

                if p:

                    p["priority"] = bases[ti] + i

    cfgmod.mutate(mut)

    return {"ok": True}





# ---- 窗口控制（前端“点 ✕ 确认框”使用） ----



@app.post("/api/window/hide")

async def window_hide(_=Depends(api_auth)):

    """隐藏主窗口到托盘（服务继续运行）。"""

    try:

        if window_ref:

            window_ref.hide()

        return {"ok": True}

    except Exception as e:

        return {"ok": False, "error": str(e)[:200]}





@app.post("/api/window/quit")

async def window_quit(_=Depends(api_auth)):

    """真正退出程序（托盘图标一并移除）。"""

    try:

        if srv_ref:

            srv_ref.should_exit = True

        if tray_ref:

            try:

                tray_ref.stop()

            except Exception:

                pass

        if window_ref:

            window_ref.destroy()

        return {"ok": True}

    except Exception as e:

        return {"ok": False, "error": str(e)[:200]}



@app.post("/api/open-url")

async def open_url(req: Request, _=Depends(api_auth)):

    """在系统默认浏览器中打开指定 URL。"""

    import webbrowser

    try:

        body = await req.json()

        url = (body.get("url") or "").strip()

        if not url.startswith("http"):

            return {"ok": False, "error": "invalid url"}

        webbrowser.open(url)

        return {"ok": True}

    except Exception as e:

        return {"ok": False, "error": str(e)[:200]}





# ---- 开机自启 ----



def _autostart_cmd():

    if getattr(sys, "frozen", False):

        return [sys.executable, "--no-ui"]

    py = sys.executable

    if os.name == "nt":

        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")

        if os.path.exists(pyw):

            py = pyw

    return [py, os.path.abspath(sys.argv[0]), "--no-ui"]





def _autostart_enabled() -> bool:

    try:

        if os.name == "nt":

            import winreg

            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")

            try:

                winreg.QueryValueEx(k, "LLMGateway")

                return True

            finally:

                winreg.CloseKey(k)

        else:

            return (Path.home() / ".config/autostart/llm-gateway.desktop").exists()

    except Exception:

        return False





def _autostart_set(on: bool) -> None:

    if os.name == "nt":

        import winreg

        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,

                           r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)

        try:

            if on:

                cmd = " ".join(f'"{a}"' for a in _autostart_cmd())

                winreg.SetValueEx(k, "LLMGateway", 0, winreg.REG_SZ, cmd)

            else:

                try:

                    winreg.DeleteValue(k, "LLMGateway")

                except FileNotFoundError:

                    pass

        finally:

            winreg.CloseKey(k)

    else:

        d = Path.home() / ".config/autostart"

        d.mkdir(parents=True, exist_ok=True)

        f = d / "llm-gateway.desktop"

        if on:

            cmd = " ".join("'" + a + "'" for a in _autostart_cmd())

            f.write_text("[Desktop Entry]\nType=Application\nName=LLM Gateway\nExec="

                         + cmd + "\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")

        elif f.exists():

            f.unlink()





@app.get("/api/autostart")

async def autostart_get(_=Depends(api_auth)):

    return {"enabled": _autostart_enabled()}





@app.post("/api/autostart")

async def autostart_post(req: Request, _=Depends(api_auth)):

    b = await req.json()

    on = bool(b.get("enabled"))

    try:

        _autostart_set(on)

    except Exception as e:

        return {"ok": False, "error": str(e)[:200]}

    return {"ok": True, "enabled": on}





# ---- 冷却池 / 日志 ----



@app.post("/api/cooldowns/clear")

async def cooldowns_clear(req: Request, _=Depends(api_auth)):

    try:

        b = await req.json()

    except Exception:

        b = {}

    state_mod.clear(b.get("key"))

    return {"ok": True}





@app.get("/api/logs/export")

async def logs_export(_=Depends(api_auth)):

    """导出全部请求日志（JSON 附件下载）。"""

    state_mod.maybe_persist()

    data = {"exported_at": time.time(), "count": len(state_mod.LOGS), "logs": list(state_mod.LOGS)}

    return Response(content=json.dumps(data, ensure_ascii=False, indent=2),

                    media_type="application/json",

                    headers={"Content-Disposition": "attachment; filename=llm-gateway-logs.json"})





@app.post("/api/logs/clear")

async def logs_clear(_=Depends(api_auth)):

    state_mod.LOGS.clear()

    state_mod.persist()

    return {"ok": True}





# ---- 配置导入导出 ----



@app.get("/api/config/export")

async def config_export(_=Depends(api_auth)):

    c = copy.deepcopy(cfgmod.cfg())

    c.pop("_pending_restart", None)

    return Response(content=json.dumps(c, ensure_ascii=False, indent=2),

                    media_type="application/json",

                    headers={"Content-Disposition": "attachment; filename=llm-gateway-config.json"})





@app.post("/api/config/import")

async def config_import(req: Request, _=Depends(api_auth)):

    try:

        b = await req.json()

    except Exception:

        raise StarletteHTTPException(400, "配置文件不是合法 JSON")

    if not isinstance(b, dict):

        raise StarletteHTTPException(400, "配置文件格式不正确")

    base = cfgmod.defaults()

    if b.get("mode") in ("smart", "safe"):

        base["mode"] = b["mode"]

    for sect in ("server", "routing", "cooldown"):

        v = b.get(sect)

        if isinstance(v, dict):

            for k, val in v.items():

                if k in base[sect]:

                    base[sect][k] = val

    for sect in ("providers", "aliases"):

        v = b.get(sect)

        if isinstance(v, list):

            base[sect] = v

    if not base["server"].get("key"):

        hist = base["server"].setdefault("key_history", [])

        base["server"]["key"] = cfgmod.new_key(hist)

        hist.append(base["server"]["key"])

    if not base["server"].get("port"):

        base["server"]["port"] = cfgmod.random_free_port(base["server"].get("host") or "127.0.0.1")

    cfgmod.replace(base)

    if (base["server"].get("port") != STARTUP_PORT or

            base["server"].get("host") != STARTUP_HOST):

        cfgmod.mutate(lambda c: c.__setitem__("_pending_restart", True))

    return {"ok": True}





# ---------------------------------------------------------------- 静态面板



app.mount("/", StaticFiles(directory=str(_web_dir()), html=True), name="web")

