"""常见服务商预设。标记为「可信」的渠道在「安全路由」模式下才可被调度。"""

PRESETS = [
    # ---- 可信渠道（安全路由可用） ----
    {"name": "DeepSeek 深度求索", "base_url": "https://api.deepseek.com/v1", "adapter": "openai", "trusted": True},
    {"name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "adapter": "openai", "trusted": True},
    {"name": "Moonshot Kimi", "base_url": "https://api.moonshot.cn/v1", "adapter": "openai", "trusted": True},
    {"name": "阿里云百炼（通义千问）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "adapter": "openai", "trusted": True},
    {"name": "火山方舟（豆包）", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "adapter": "openai", "trusted": True},
    {"name": "硅基流动 SiliconFlow", "base_url": "https://api.siliconflow.cn/v1", "adapter": "openai", "trusted": True},
    {"name": "MiniMax", "base_url": "https://api.minimaxi.com/v1", "adapter": "openai", "trusted": True},
    {"name": "腾讯混元", "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "adapter": "openai", "trusted": True},
    {"name": "阶跃星辰 StepFun", "base_url": "https://api.stepfun.com/v1", "adapter": "openai", "trusted": True},
    {"name": "零一万物 Yi", "base_url": "https://api.lingyiwanwu.com/v1", "adapter": "openai", "trusted": True},
    {"name": "百度千帆", "base_url": "https://qianfan.baidubce.com/v2", "adapter": "openai", "trusted": True},
    {"name": "讯飞星火", "base_url": "https://spark-api-open.xf-yun.com/v1", "adapter": "openai", "trusted": True},
    # ---- 其他渠道 ----
    {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "adapter": "openai", "trusted": False},
    {"name": "Anthropic", "base_url": "https://api.anthropic.com", "adapter": "anthropic", "trusted": False},
    {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "adapter": "openai", "trusted": False},
    {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "adapter": "openai", "trusted": False},
    {"name": "Groq", "base_url": "https://api.groq.com/openai/v1", "adapter": "openai", "trusted": False},
    {"name": "xAI Grok", "base_url": "https://api.x.ai/v1", "adapter": "openai", "trusted": False},
    {"name": "Mistral", "base_url": "https://api.mistral.ai/v1", "adapter": "openai", "trusted": False},
    {"name": "Together", "base_url": "https://api.together.xyz/v1", "adapter": "openai", "trusted": False},
]
