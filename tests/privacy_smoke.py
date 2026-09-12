"""脱密路由三层行为测试：L1 正则（gitleaks/llm-guard 规则）、L2 敏感词库、
L3 实体识别（注入假后端 + jieba 引擎检查）、流式跨事件回填、端到端
（普通渠道脱密 / 可信渠道原文 / OpenAI 与 Anthropic 双协议 / 流式）。

    python tests/privacy_smoke.py
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
sys.path.insert(0, str(ROOT))

PY = sys.executable
GW_PORT = 38231
GW = f"http://127.0.0.1:{GW_PORT}"
KEY = "sk-lg-" + "b" * 48
ECHO_MASK, ECHO_TRUST = 9311, 9312

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + (f"  [{detail}]" if detail and not cond else ""))


def wait_health(url, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(url, timeout=2, trust_env=False).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def recv(client, port):
    return httpx.get(f"http://127.0.0.1:{port}/received", timeout=10, trust_env=False).json()["last_body"]


def last_user(body):
    return body["messages"][-1]["content"]


def unit_tests():
    print("— 单元：三层脱密引擎 —")
    from app import ner, privacy

    privacy._STABLE_SEQ.clear()
    privacy._CAT_SEQ.clear()

    # 有效身份证号（按校验位现场计算）
    W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    base = "11010519491231002"
    cnid = base + "10X98765432"[sum(int(c) * W[i] for i, c in enumerate(base)) % 11]

    # 有效统一社会信用代码（按 ISO 7064 现场计算校验位）
    CH = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    WIU = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]
    base17 = "91450300765957283"
    uscc = base17 + CH[(31 - sum(CH.index(c) * WIU[i] for i, c in enumerate(base17)) % 31) % 31]

    cfg = {"mode": "mask", "privacy": {
        "rules": {"api_keys": True, "key_value_pairs": True, "emails": True,
                  "phones": True, "id_cards": True, "uscc": True,
                  "private_keys": True, "bank_cards": True},
        "glossary": [{"term": "启元科技", "category": "company"},
                     {"term": "星辰计划", "category": "project"},
                     {"term": "张三", "category": "person"},
                     {"term": "ProjectX", "category": "project"}],
        "extra_words": ["re:TESTC-[A-Za-z0-9/-]+", "re:某某综字第\\d+号"],
        "ner_entities": False,
    }}
    ms = privacy.make_session(cfg)
    text = (f"密钥 sk-test-abcdef1234567890ab12 / sk-ant-api03-xyz-{'k' * 40} / "
            f"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4 / "
            f"Bearer abcdef1234567890abcdef / AKIAIOSFODNN7EXAMPLE / AIza"
            f"{'A' * 29}x9 / ghp_{'G' * 18}{'h' * 18} / sk_live_abcdef12345 / "
            f"xoxb-abcdefgh1234-zyxwvu987654-abcdefghijklmnopqrst / \\d:AA "
            f"123456:AA{'T' * 33} / SG.abcdefgh23456789.ijklmnop01234567 / "
            f"npm_{'a' * 36} / pypi-AgEIcHlwaS5vcmc{'z' * 55} / hf_{'q' * 34} / "
            f"https://user:secretpass@api.example.com/v1 / "
            f"api_key=abcdef123456 / {cnid} / {uscc} / 0771-1234567 / "
            f"TESTC-EN09JL01/A01436 / （某省）某某综字第20250001号 / "
            f"4012888888881881 / "
            f"-----BEGIN RSA PRIVATE KEY-----\nMIIB{'x' * 100}\n-----END RSA PRIVATE KEY-----\n"
            f"联系 boss@qiyuan.cn 或 13812345678，关于启元科技和星辰计划，张三负责ProjectX。")
    masked = ms.mask_text(text)
    for kw, name in [("sk-test-", "sk- 系密钥"), ("eyJhbGciOi", "JWT"), ("AKIAIOSFODNN7", "AWS Key"),
                     ("ghp_", "GitHub token"), ("sk_live_", "Stripe key"), ("xoxb-", "Slack token"),
                     ("api.example.com", "URL 内嵌凭据"), ("api_key=", "键值对"),
                     ("boss@qiyuan.cn", "邮箱"), ("13812345678", "手机号"), ("BEGIN RSA", "私钥块"),
                     ("4111111111111111"[:0], "")]:
        if not kw:
            continue
        check(f"L1 识别 {name}", kw not in masked)
    check("L1 识别身份证号(校验位通过)", cnid not in masked, cnid)
    check("L1 识别统一社会信用代码(校验位通过)", uscc not in masked, uscc)
    check("L1 识别座机", "0771-1234567" not in masked)
    check("L2 extra_words 正则(报告编号)", "TESTC-EN09JL01" not in masked)
    check("L2 extra_words 正则(综字号)", "20250001号" not in masked)
    check("L1 银行卡(Luhn)", "4012888888881881" not in masked)
    check("L2 词库-公司/项目/人名", all(x not in masked for x in ("启元科技", "星辰计划", "张三")))
    check("L2 词库-ASCII 边界", "ProjectX" not in masked)
    check("占位符生成", "[公司1]" in masked and "[项目1]" in masked and "[人名1]" in masked and "[SEC-1]" in masked)
    check("响应回填(还原完整原文)", ms.restore_text(masked) == text)

    # 无效校验位的身份证号不应误报
    ms2 = privacy.make_session(cfg)
    bad = "110105194912310021"  # 末位故意错
    check("L1 身份证校验位降噪", ms2.mask_text(f"号码 {bad} 备案") == f"号码 {bad} 备案")

    # L2 稳定编号：跨会话同词条同占位符
    ms3 = privacy.make_session(cfg)
    t3 = ms3.mask_text("启元科技发布公告")
    check("L2 占位符全局稳定(跨请求一致)", "[公司1]" in t3, t3)

    # 关闭规则组
    cfg_off = json.loads(json.dumps(cfg))
    cfg_off["privacy"]["rules"]["emails"] = False
    ms4 = privacy.make_session(cfg_off)
    check("规则组可关闭", "a@b.cn" in ms4.mask_text("邮箱 a@b.cn"))

    # jieba 引擎真实可用（在注入假后端之前检查）
    check("L3 jieba 引擎就绪", privacy.ner_name() in ("jieba", "lac"), privacy.ner_name())

    # L3：注入假 NER 后端（占位符编号全局稳定，此处应为 公司2）
    from app import ner as ner_mod
    ner_mod.set_backend_for_test("fake", lambda t: [(0, 4, "company")] if t.startswith("字节") else [])
    ms5 = privacy.make_session({"mode": "mask", "privacy": {"ner_entities": True}})
    m5 = ms5.mask_text("字节跳动发布了新模型")
    check("L3 实体识别(注入后端)", "字节跳动" not in m5 and "[公司" in m5, m5)
    check("L3 回填", ms5.restore_text(m5) == "字节跳动发布了新模型")
    ner_mod.set_backend_for_test("none", None)
    ner_mod._loaded = False  # 恢复真实后端探测

    # 流式跨事件回填（占位符被切成 3 字符一片）
    ms6 = privacy.make_session({"mode": "mask", "privacy": {
        "rules": {"api_keys": True},
        "glossary": [{"term": "星辰计划", "category": "project"}]}})
    body = {"messages": [{"role": "user", "content": "推进星辰计划，密钥 sk-test-abcdef1234567890ab"}]}
    masked_full = privacy.mask_body(ms6, body)["messages"][0]["content"]
    sr = privacy.StreamRestorer(ms6)
    out = ""
    for i in range(0, len(masked_full), 3):
        ev = {"choices": [{"delta": {"content": masked_full[i:i + 3]}}]}
        out += json.loads(sr.feed(json.dumps(ev, ensure_ascii=False)))["choices"][0]["delta"]["content"]
    check("流式跨事件回填", "星辰计划" in out and "sk-test-abcdef1234567890ab" in out, out)

    # tool_calls 参数里的占位符也要回填
    resp = {"choices": [{"message": {"role": "assistant", "content": "",
                                     "tool_calls": [{"id": "t1", "type": "function",
                                                     "function": {"name": "write", "arguments":
                                                                  json.dumps({"path": "k.txt", "content": "key=[SEC-1]"})}}]}}]}
    # 会话 ms6 的 [SEC-1] = sk-test-abcdef1234567890ab
    check("tool 参数回填", "sk-test-abcdef1234567890ab" in json.dumps(privacy.restore_out(ms6, resp), ensure_ascii=False))


def e2e_tests():
    print("— 端到端：普通渠道脱密 / 可信渠道原文 / 双协议 / 流式 —")
    home = tempfile.mkdtemp(prefix="llm-gw-privacy-")
    procs = []
    try:
        cfg = {
            "version": 1, "mode": "mask",
            "server": {"host": "127.0.0.1", "port": GW_PORT, "key": KEY, "key_history": [KEY]},
            "routing": {"strategy": "site_first", "max_attempts": 4, "timeout_seconds": 30},
            "cooldown": {"base_seconds": 5, "max_seconds": 30},
            "privacy": {"restore": True, "ner_entities": True,
                        "rules": {"api_keys": True, "key_value_pairs": True, "emails": True,
                                  "phones": True, "id_cards": True, "private_keys": True,
                                  "bank_cards": False},
                        "glossary": [{"term": "启元科技", "category": "company"},
                                     {"term": "星辰计划", "category": "project"},
                                     {"term": "张三", "category": "person"}]},
            "providers": [
                {"id": "p_mask", "name": "普通渠道", "base_url": f"http://127.0.0.1:{ECHO_MASK}/v1",
                 "api_key": "k", "adapter": "openai", "enabled": True, "priority": 1, "note": "",
                 "fetched_models": ["mock-chat"], "sched_models": ["mock-chat"], "last_test": None},
                {"id": "p_trust", "name": "可信渠道", "base_url": f"http://127.0.0.1:{ECHO_TRUST}/v1",
                 "api_key": "k", "adapter": "openai", "enabled": True, "priority": 2, "trusted": True,
                 "note": "", "fetched_models": ["mock-chat"], "sched_models": ["mock-chat"], "last_test": None},
            ],
            "aliases": [],
        }
        (Path(home) / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")

        def start(cmd, env=None):
            e = os.environ.copy()
            e.update(env or {})
            return subprocess.Popen(cmd, env=e, cwd=str(ROOT),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        procs.append(start([PY, "tests/echo_upstream.py", str(ECHO_MASK)]))
        procs.append(start([PY, "tests/echo_upstream.py", str(ECHO_TRUST)]))
        procs.append(start([PY, "main.py", "--no-ui"],
                           env={"LLM_GATEWAY_HOME": home, "NO_PROXY": "127.0.0.1,localhost"}))
        assert wait_health(GW + "/health"), "网关未能启动"
        time.sleep(0.5)
        c = httpx.Client(base_url=GW, trust_env=False, timeout=30,
                         headers={"Authorization": "Bearer " + KEY})

        W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        base = "11010519491231002"
        cnid = base + "10X98765432"[sum(int(ch) * W[i] for i, ch in enumerate(base)) % 11]
        content = (f"密钥 sk-test-abcdef1234567890ab12，邮箱 boss@qiyuan.cn，电话 13812345678，"
                   f"身份证 {cnid}。请帮启元科技的张三推进星辰计划。")

        st = c.get("/api/state").json()
        check("状态接口含脱密引擎信息", st.get("privacy_status", {}).get("ner") in ("jieba", "lac"),
              str(st.get("privacy_status")))

        # 1. 非流式：上游看到占位符，客户端拿到原文
        r = c.post("/v1/chat/completions", json={"model": "mock-chat", "messages": [{"role": "user", "content": content}]})
        check("非流式请求 200", r.status_code == 200, r.text[:200])
        up = last_user(recv(c, ECHO_MASK))
        check("上游只见占位符", "[SEC-1]" in up and "[公司1]" in up and "[项目1]" in up and "[人名1]" in up, up)
        check("上游无任何原文敏感值", not any(x in up for x in ("sk-test-", "boss@qiyuan.cn", "13812345678", cnid, "启元科技", "星辰计划", "张三")), up)
        out = r.json()["choices"][0]["message"]["content"]
        check("客户端拿到回填原文", "启元科技" in out and "星辰计划" in out and "张三" in out and cnid in out, out)
        check("客户端无占位符残留", "[SEC-" not in out and "[公司" not in out, out)

        # 2. 跨请求占位符稳定
        c.post("/v1/chat/completions", json={"model": "mock-chat", "messages": [{"role": "user", "content": "启元科技怎么样？"}]})
        up2 = last_user(recv(c, ECHO_MASK))
        check("跨请求占位符稳定([公司1])", "[公司1]" in up2 and "启元科技" not in up2, up2)

        # 3. 流式：占位符被 7 字符分片，客户端拼接后应完整回填
        chunks = []
        with c.stream("POST", "/v1/chat/completions", json={"model": "mock-chat", "stream": True,
                                                            "messages": [{"role": "user", "content": content}]}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    d = json.loads(line[6:])
                    chunks.append(d["choices"][0]["delta"].get("content") or "")
        check("流式回填完整", "启元科技" in "".join(chunks) and "[SEC-" not in "".join(chunks), "".join(chunks)[:120])

        # 4. Anthropic 方言（/v1/messages）非流式
        r = c.post("/v1/messages", json={"model": "mock-chat", "max_tokens": 100,
                                         "messages": [{"role": "user", "content": "启元科技的密钥 sk-test-abcdef1234567890ab12"}]})
        up3 = json.dumps(last_user(recv(c, ECHO_MASK)), ensure_ascii=False)
        check("anthropic 上游脱密", "sk-test-" not in up3 and "[公司1]" in up3, up3)
        aout = json.dumps(r.json(), ensure_ascii=False)
        check("anthropic 客户端回填", r.status_code == 200 and "启元科技" in aout and "sk-test-abcdef1234567890ab12" in aout, aout[:200])

        # 5. Anthropic 方言流式
        pieces = []
        with c.stream("POST", "/v1/messages", json={"model": "mock-chat", "max_tokens": 100, "stream": True,
                                                    "messages": [{"role": "user", "content": content}]}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    ev = json.loads(line[6:])
                    if ev.get("type") == "content_block_delta":
                        pieces.append((ev.get("delta") or {}).get("text") or "")
        astream = "".join(pieces)
        check("anthropic 流式回填", "星辰计划" in astream and "启元科技" in astream and "[SEC-" not in astream, astream[:120])

        # 6. 可信渠道：原文直通
        check("停用普通渠道", c.put("/api/providers/p_mask", json={"enabled": False}).status_code == 200)
        r = c.post("/v1/chat/completions", json={"model": "mock-chat", "messages": [{"role": "user", "content": content}]})
        up4 = last_user(recv(c, ECHO_TRUST))
        check("可信渠道原文直通", "sk-test-abcdef1234567890ab12" in up4 and "启元科技" in up4 and cnid in up4, up4[:150])
        check("可信渠道客户端也拿原文", "sk-test-abcdef1234567890ab12" in r.json()["choices"][0]["message"]["content"])
        c.put("/api/providers/p_mask", json={"enabled": True})

        # 7. 切回智能路由：不再脱密
        c.post("/api/settings", json={"mode": "smart"})
        c.post("/v1/chat/completions", json={"model": "mock-chat", "messages": [{"role": "user", "content": content}]})
        up5 = last_user(recv(c, ECHO_MASK))
        check("智能路由不脱密", "sk-test-abcdef1234567890ab12" in up5 and "启元科技" in up5, up5[:150])

        # 8. 设置接口：词库/规则持久化（脏数据被清洗）
        r = c.post("/api/settings", json={"mode": "mask", "privacy": {
            "glossary": [{"term": "星辰计划", "category": "project"},
                         {"term": "", "category": "company"}, "junk",
                         {"term": "某公司", "category": "不存在"}],
            "rules": {"bank_cards": True}}})
        pv2 = c.get("/api/state").json()["config"].get("privacy") or {}
        check("设置接口保存词库与规则",
              r.status_code == 200 and pv2.get("glossary") == [
                  {"term": "星辰计划", "category": "project"},
                  {"term": "某公司", "category": "custom"}] and pv2.get("rules", {}).get("bank_cards") is True,
              json.dumps(pv2, ensure_ascii=False)[:200])

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
    unit_tests()
    e2e_tests()
