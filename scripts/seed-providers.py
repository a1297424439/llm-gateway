# -*- coding: utf-8 -*-
"""LLM Gateway 渠道骨架恢复脚本（v1.0.5+）。
用法：先确保无 llm-gateway 进程在运行，再执行本脚本；之后启动网关。
只重建 base_url 可确认的渠道，api_key 留空由用户在面板补充。
"""
import json
import os
import secrets

APPDATA = os.environ["APPDATA"]
cfg_path = os.path.join(APPDATA, "LLMGateway", "config.json")

with open(cfg_path, encoding="utf-8-sig") as f:
    cfg = json.load(f)

cfg.setdefault("server", {})["port"] = 33308
cfg.setdefault("routing", {})["max_attempts"] = 4
cfg.pop("_pending_restart", None)

SKELETONS = [
    {"name": "ShareLLM 中转 ①", "base_url": "https://sharellm.cn/v1",
     "priority": 1, "sched_models": ["kimi-k3", "qwen3.8-max", "deepseek-v4-pro-0813",
                                      "deepseek-v4-flash-vision", "glm-5.3-flash",
                                      "deepseek-v4-flash", "deepseek-v4-flash-0731"]},
    {"name": "JustWoker Claude 中转", "base_url": "https://api.justwoker.icu/v1/chat/completions",
     "priority": 3, "sched_models": ["claude-opus-5-thinking", "claude-opus-5"]},
    {"name": "TokenRhythm Studio", "base_url": "https://ayase.cn/simple-api/v1",
     "priority": 10, "sched_models": ["glm-5.3-flash", "deepseek-v4-flash-0731"]},
    {"name": "DeepSeek 官方", "base_url": "https://api.deepseek.com",
     "priority": 20, "sched_models": ["deepseek-v4-flash"]},
]

providers = cfg.setdefault("providers", [])
existing = {p.get("name") for p in providers}
added = []
for sk in SKELETONS:
    if sk["name"] in existing:
        continue
    providers.append({
        "id": "p_" + secrets.token_hex(4),
        "name": sk["name"],
        "base_url": sk["base_url"],
        "api_key": "",
        "adapter": "openai",
        "trusted": False,
        "enabled": True,
        "priority": sk["priority"],
        "note": "骨架恢复，需在面板补充 api_key",
        "fetched_models": [],
        "sched_models": sk["sched_models"],
        "last_test": None,
    })
    added.append(sk["name"])

with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print("added:", added or "（已存在，跳过）")
print("total providers:", len(providers), "| port:", cfg["server"]["port"],
      "| key set:", bool(cfg["server"].get("key")), "| max_attempts:", cfg["routing"]["max_attempts"])
