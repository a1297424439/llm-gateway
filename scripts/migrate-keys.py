# -*- coding: utf-8 -*-
"""从 Hermes config.yaml 迁移渠道 api_key 到 LLM Gateway（文件对文件，不回显密钥）。
走 gateway API（PUT /api/providers/{pid}）→ 内存配置即时生效，无需重启。
随后逐个渠道 refresh 测试连通性。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

APPDATA = os.environ["APPDATA"]
HERMES_CFG = r"C:\Users\Administrator\AppData\Local\Hermes Agent CN Desktop\data\hermes-home\config.yaml"
GATEWAY = "http://127.0.0.1:33308"

gateway_cfg = json.load(open(os.path.join(APPDATA, "LLMGateway", "config.json"), encoding="utf-8-sig"))
GW_KEY = gateway_cfg["server"]["key"]

# ---- 1. parse Hermes config.yaml: block name -> (base_url, api_key) ----
blocks = {}  # name -> {"base_url":..., "api_key":...}
cur = None
with open(HERMES_CFG, encoding="utf-8") as f:
    lines = f.read().splitlines()
for line in lines:
    m = re.match(r"^(\s*)(custom:[\w-]+|[A-Za-z][\w-]*):\s*$", line)
    if m and len(m.group(1)) in (0, 2):
        cur = m.group(2)
        blocks.setdefault(cur, {})
        continue
    if cur is None:
        continue
    m = re.match(r"^\s{2,}base_url:\s*(\S+)\s*$", line)
    if m:
        blocks[cur]["base_url"] = m.group(1)
        continue
    m = re.match(r"^\s{2,}api_key:\s*(\S+)\s*$", line)
    if m:
        blocks[cur]["api_key"] = m.group(1).strip("\"'")
        continue
    if line and not line.startswith((" ", "\t")):
        cur = None  # next top-level section

# ---- 2. match gateway providers by normalized base_url ----
def norm(u):
    return (u or "").rstrip("/").lower()

def api(path, method="GET", body=None):
    req = urllib.request.Request(GATEWAY + path, method=method)
    req.add_header("Authorization", "Bearer " + GW_KEY)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    else:
        data = None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:300]

st, state = api("/api/state")
providers = state["config"]["providers"]

def matched_key_hint(k):
    return f"sk-…{k[-4:]}" if k.startswith("sk-") else f"…{k[-4:]}"

filled, skipped = [], []
for p in providers:
    pu = norm(p.get("base_url"))
    matched = None
    for name, b in blocks.items():
        if b.get("base_url") and norm(b["base_url"]) == pu:
            matched = b
            break
    if not matched or not matched.get("api_key"):
        skipped.append((p["name"], "无匹配 key"))
        continue
    code, resp = api(f"/api/providers/{p['id']}", method="PUT", body={"api_key": matched["api_key"]})
    if code == 200:
        filled.append(p["name"])
        print(f"  [填] {p['name']} <- Hermes 配置（{matched_key_hint(matched['api_key'])}）")
    else:
        skipped.append((p["name"], f"PUT 失败 {code} {str(resp)[:80]}"))

def matched_key_hint(k):
    return f"sk-…{k[-4:]}" if k.startswith("sk-") else f"…{k[-4:]}"

print("已填:", filled)
print("跳过:", skipped)

# ---- 3. refresh test each provider ----
print("\n== 渠道连通性测试 ==")
for p in providers:
    code, resp = api(f"/api/providers/{p['id']}/refresh", method="POST")
    if code == 200 and resp.get("ok"):
        print(f"  [可用] {p['name']}: {len(resp.get('models') or [])} 个模型")
    else:
        print(f"  [失败] {p['name']}: {str(resp.get('error'))[:120]}")
