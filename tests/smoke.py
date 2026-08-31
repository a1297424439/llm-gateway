"""端到端冒烟测试：启动 mock 上游 + 网关，验证鉴权、直连模型名调度、故障转移、
冷却池、流式、安全模式、上下文识别。

    python tests/smoke.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
GW_PORT = 38127
GW = f"http://127.0.0.1:{GW_PORT}"
KEY = "sk-lg-" + "a" * 48

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + (f"  [{detail}]" if detail and not cond else ""))


def wait_health(url, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = httpx.get(url, timeout=2, trust_env=False)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def start(cmd, env=None):
    e = os.environ.copy()
    e.update(env or {})
    return subprocess.Popen(cmd, env=e, cwd=str(ROOT),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def gw_headers():
    return {"Authorization": "Bearer " + KEY}


def main():
    home = tempfile.mkdtemp(prefix="llm-gw-test-")
    procs = []
    try:
        cfg = {
            "version": 1, "mode": "smart",
            "server": {"host": "127.0.0.1", "port": GW_PORT, "key": KEY, "key_history": [KEY]},
            "routing": {"strategy": "site_first", "max_attempts": 4, "timeout_seconds": 30,
                        "whitelist_enabled": False, "whitelist": [], "whitelist_fallback": True},
            "cooldown": {"base_seconds": 5, "max_seconds": 30},
            "providers": [
                {"id": "p_bad", "name": "坏渠道", "base_url": "http://127.0.0.1:9302/v1",
                 "api_key": "k", "adapter": "openai", "trusted": False, "enabled": True,
                 "priority": 1, "note": "", "priority_note": "",
                 "fetched_models": ["mock-chat", "mock-embed", "secret-model"],
                 "sched_models": ["mock-chat", "mock-embed"],
                 "model_context": {"mock-chat": 1000000, "mock-embed": 1000000, "secret-model": 1000000},
                 "last_test": None},
                {"id": "p_ok", "name": "好渠道", "base_url": "http://127.0.0.1:9301/v1",
                 "api_key": "k", "adapter": "openai", "trusted": True, "enabled": True,
                 "priority": 2, "note": "",
                 "fetched_models": ["mock-chat", "mock-embed"],
                 "sched_models": ["mock-chat", "mock-embed"],
                 "model_context": {"mock-chat": 1024000, "mock-embed": 500000},
                 "last_test": None},
            ],
            "aliases": [],
        }
        (Path(home) / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")

        procs.append(start([PY, "tests/mock_upstream.py", "9301", "ok"]))
        procs.append(start([PY, "tests/mock_upstream.py", "9302", "fail"]))
        procs.append(start([PY, "main.py", "--no-ui"],
                           env={"LLM_GATEWAY_HOME": home, "NO_PROXY": "127.0.0.1,localhost"}))
        print("等待服务启动…")
        assert wait_health(GW + "/health"), "网关未能启动"
        print("服务已就绪，开始断言：")

        c = httpx.Client(base_url=GW, trust_env=False, timeout=30)

        # 1. 鉴权
        r = c.get("/v1/models")
        check("未携带 Key 返回 401", r.status_code == 401, str(r.status_code))
        r = c.get("/v1/models", headers={"Authorization": "Bearer wrong"})
        check("错误 Key 返回 401", r.status_code == 401, str(r.status_code))
        r = c.get("/v1/models", headers=gw_headers())
        m0 = r.json()["data"]
        ids = [m["id"] for m in m0]
        auto_entry = next(m for m in m0 if m["id"] == "auto")
        check("模型列表=auto+勾选模型并集", r.status_code == 200 and set(ids) == {"auto", "mock-chat", "mock-embed"}, str(ids))
        check("auto 标注上下文(取勾选最小值)", auto_entry.get("context_length") == 500000, str(auto_entry))

        # 2. 非流式 + auto 虚拟模型 + 故障转移（坏渠道档位 1，应失败后切到好渠道）
        r = c.post("/v1/chat/completions", headers=gw_headers(),
                   json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
        ok = r.status_code == 200 and "mock-9301" in r.json()["choices"][0]["message"]["content"]
        check("auto 模型按档位调度成功", ok, r.text[:200])
        logs0 = c.get("/api/state").json()["logs"]
        check("auto 请求日志记录用量", isinstance((logs0[0].get("usage") or {}).get("c"), int), str(logs0[0].get("usage")))
        r = c.post("/v1/chat/completions", headers=gw_headers(),
                   json={"model": "mock-chat", "messages": [{"role": "user", "content": "hi"}]})
        ok = r.status_code == 200 and "mock-9301" in r.json()["choices"][0]["message"]["content"]
        check("直连模型名经故障转移成功", ok, r.text[:200])

        # 3. 冷却池
        cds = c.get("/api/state").json()["cooldowns"]
        check("失败模型进入冷却池", any(x["provider_id"] == "p_bad" for x in cds), json.dumps(cds))

        r = c.post("/v1/chat/completions", headers=gw_headers(),
                   json={"model": "mock-chat", "messages": [{"role": "user", "content": "hi"}]})
        check("冷却期间调度下一档渠道", r.status_code == 200 and "mock-9301" in r.text[:400])
        logs = c.get("/api/state").json()["logs"]
        atts = (logs[0].get("attempts") or []) if logs else []
        check("调度日志记录跳过冷却", any(a.get("skipped") for a in atts), json.dumps(atts))

        # 4. 流式
        chunks = []
        with c.stream("POST", "/v1/chat/completions", headers=gw_headers(),
                      json={"model": "mock-chat", "stream": True,
                            "messages": [{"role": "user", "content": "hi"}]}) as r:
            check("流式请求 200", r.status_code == 200)
            for line in r.iter_lines():
                if line.startswith("data: "):
                    chunks.append(line[6:])
        text = "".join(chunks)
        check("流式内容包含 mock 回复与 [DONE]", "mock-9301" in text and "[DONE]" in text, text[:200])

        # 5. embeddings
        r = c.post("/v1/embeddings", headers=gw_headers(),
                   json={"model": "mock-embed", "input": "test"})
        check("embeddings 透传", r.status_code == 200 and "embedding" in r.text, r.text[:200])

        # 6. 未勾选/未知模型
        r = c.post("/v1/chat/completions", headers=gw_headers(),
                   json={"model": "secret-model", "messages": [{"role": "user", "content": "hi"}]})
        msg = r.json().get("error", {}).get("message", "")
        check("存在于渠道但未勾选 → 404 且提示勾选", r.status_code == 404 and "未勾选调度" in msg, msg[:120])
        r = c.post("/v1/chat/completions", headers=gw_headers(),
                   json={"model": "nope", "messages": [{"role": "user", "content": "hi"}]})
        check("完全未知的模型 → 404", r.status_code == 404, str(r.status_code))

        # 7. 安全模式
        c.post("/api/settings", headers=gw_headers(), json={"mode": "safe"})
        r = c.post("/v1/chat/completions", headers=gw_headers(),
                   json={"model": "mock-chat", "messages": [{"role": "user", "content": "hi"}]})
        check("安全模式下可信渠道可用", r.status_code == 200 and "mock-9301" in r.text[:400])
        r = c.get("/v1/models", headers=gw_headers())
        check("安全模式模型列表过滤（仅可信渠道勾选项）", r.status_code == 200 and
              set(m["id"] for m in r.json()["data"]) == {"auto", "mock-chat", "mock-embed"}, r.text[:200])
        c.post("/api/settings", headers=gw_headers(), json={"mode": "smart"})

        # 8. 勾选管理 API
        r = c.put("/api/providers/p_bad", headers=gw_headers(), json={"sched_models": ["secret-model"]})
        check("更新勾选列表", r.status_code == 200)
        r = c.get("/v1/models", headers=gw_headers())
        check("勾选变更即时生效", "secret-model" in [m["id"] for m in r.json()["data"]])

        # 9. 上下文识别
        st = c.get("/api/state", headers=gw_headers()).json()
        p_ok = next(p for p in st["config"]["providers"] if p["id"] == "p_ok")
        check("精确上下文标注", p_ok["model_ctx"]["mock-chat"] == [1024000, True], str(p_ok["model_ctx"]))
        check("渠道标注外的模型不臆造上下文",
              set(p_ok["model_ctx"].keys()) == {"mock-chat", "mock-embed"}, str(p_ok["model_ctx"].keys()))
        r = c.post("/api/server/regenerate-key", headers=gw_headers())
        new_key = r.json()["key"]
        check("重新生成 Key 且与旧 Key 不同", new_key != KEY and new_key.startswith("sk-lg-"))
        r = c.get("/v1/models", headers={"Authorization": "Bearer " + KEY})
        check("旧 Key 立即失效", r.status_code == 401)

        print(f"\n结果: {len(PASS)} 通过, {len(FAIL)} 失败")
        if FAIL:
            print("失败项:", FAIL)
            sys.exit(1)
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(0.8)
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
