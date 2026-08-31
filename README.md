# LLM Gateway · 智能调度网关

**中文 | [English](README.en.md)**

一个跑在本地的 **大模型 API 智能调度器**，把多个网站/订阅服务的 API 统一成一个
OpenAI 兼容接口。自动按优先级故障转移，带 iOS 风格管理面板，Windows / Linux 通用。

> **为什么用它？** 大多数 LLM 网关默认上游是「按量付费的 API Key」。而很多人用的是
> **订阅制会员站**（月费/额度站）——额度一旦用完，请求就 502。LLM Gateway 专为这类
> 场景设计：自动识别「额度用尽」类错误，把整个渠道冷却数小时并切到下一个可用渠道。

```
客户端(Cherry Studio / LobeChat / OpenWebUI / 任意 SDK / Agent)
        │  http://127.0.0.1:<端口>/v1  + 本地随机 Key
        ▼
┌──────────────────────────────┐
│        LLM Gateway           │
│  智能路由 / 信任路由 / 冷却池  │
└──────────────────────────────┘
   │         │         └──→ 渠道 3（兜底）
   │         └────────────→ 渠道 2
   └──────────────────────→ 渠道 1（优先）
```

## 功能特性

- **多渠道接入**：添加任意多个 OpenAI 兼容 API；Anthropic 原生协议自动双向转换
  （消息格式、流式、工具调用）。
- **直连模型名调度**：客户端直接请求上游模型名，凡被勾选参与调度的渠道按档位依次
  尝试；同名模型多渠道勾选即天然互备。虚拟模型 `auto` 按档位遍历全部勾选模型。
- **双路由模式**
  - 智能路由：全部启用渠道参与调度；
  - 信任路由（安全路由）：**只调度你标记为「可信」的渠道**，由你决定信任谁。
- **双层冷却池**
  - 模型级：失败按 `base × 2ⁿ` 指数退避，封顶 max，到期半开重试；
  - 渠道级：额度类错误（402 / 余额不足 / 免费额度已用尽）触发，整渠道跳过，
    5 小时起步封顶 7 天；限流（429）60 秒起步封顶 10 分钟。
- **故障转移不截断**：`max_attempts` 按「渠道」计数，同一渠道内模型全部试完才降级。
- **双语界面**：中文 / 英文自动切换（跟随系统语言，设置页可手动切换）。
- **iOS 审美面板**：毛玻璃卡片、浅色/深色/跟随系统主题，底部 Tab 栏
  （概览 / 渠道 / 设置 / 日志）。
- **随机本地地址与 Key**：首次启动自动生成随机端口与 `sk-lg-` 密钥，可一键重生成。
- 其他：连通性测试与在线获取模型列表、请求日志与统计、配置导出/导入、流式(SSE)透传、
  embeddings 透传、开机自启、局域网监听。

## 快速开始

### 桌面软件形态

```bash
python main.py             # 桌面窗口模式（默认）
python main.py --browser   # 不弹窗口，直接浏览器打开面板
python main.py --no-ui     # 无界面服务模式，后台常驻（Ctrl+C 停止）
```

Windows 10/11 自带 WebView2；Linux 需 WebKitGTK（`sudo apt install libwebkit2gtk-4.1-dev`）。
缺失时自动回退到浏览器打开面板。

### 源码运行（Python 3.9+）

```bash
cd llm-gateway
pip install -r requirements.txt pywebview
python main.py
```

### 打包单文件

```bash
build_windows.bat                      # Windows → dist\llm-gateway.exe
chmod +x build_linux.sh && ./build_linux.sh   # Linux → dist/llm-gateway
```

## 使用指南

1. **添加渠道**：「渠道」页 → 添加渠道 → 从预设填充（自动带 Base URL / 协议 / 可信标记）
   → 填 API Key → 保存后点「获取模型列表 / 测试连通」。
2. **勾选调度模型**：渠道卡片里点击模型标签（高亮 ✓）即参与调度；拖拽卡片/标签调整
   档位与顺序（越靠上越优先）。
3. **选路由模式**：「概览」页顶部切换 智能路由 / 信任路由。
4. **接入客户端**：API 地址 `http://127.0.0.1:<端口>/v1`，模型名填上游模型名或 `auto`，
   Key 用面板显示的 `sk-lg-...`。

## API

与 OpenAI 兼容，支持 `stream: true`（SSE）：

```bash
curl http://127.0.0.1:<端口>/v1/chat/completions \
  -H "Authorization: Bearer <你的Key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"你好"}]}'
```

- `GET  /v1/models` — 模型列表（auto + 勾选模型并集）
- `POST /v1/chat/completions` — 对话补全（流式/非流式）
- `POST /v1/embeddings` — 向量（OpenAI 兼容渠道）
- `POST /v1/messages` — Anthropic Messages 协议兼容（Claude 方言客户端）
- `GET  /health` — 健康检查（免鉴权）

## 数据与配置

- 配置：`%APPDATA%\LLMGateway\config.json`（Windows）/ `~/.config/llm-gateway/config.json`（Linux）
- 运行状态（日志/冷却池）：同目录 `state.json`
- 便携模式：设置环境变量 `LLM_GATEWAY_HOME` 指向任意目录
- 「设置」页支持配置导出/导入（JSON，含密钥，注意保管）

## 常见问题

- **端口被占用？** 自动等待/改用新随机端口；面板可一键更换后重启。
- **修改监听范围（局域网）不生效？** 端口/地址修改需重启（面板有一键重启）。
- **安全提示**：默认只监听本机；开启局域网后建议非本机访问时输入 Key，勿暴露公网。
- **预设 Base URL 失效？** 以服务商官方文档为准，渠道支持自定义 URL。

## 项目结构

```
llm-gateway/
├── main.py              # 入口（随机端口/Key、重启宽限、启动横幅）
├── app/
│   ├── config.py        # 配置持久化、随机 Key/端口生成
│   ├── state.py         # 请求日志、双层冷却池（模型级+渠道级）、统计
│   ├── router.py        # 调度：档位优先、信任路由过滤
│   ├── adapters.py      # OpenAI/Anthropic 互转、SSE 解析、错误分类
│   ├── server.py        # FastAPI：/v1 网关 + /api 面板接口 + 静态页
│   └── presets.py       # 常见服务商预设（可信标记）
├── web/                 # 原生 HTML/CSS/JS 前端（含 i18n 双语）
├── tests/               # mock 上游 + 端到端冒烟测试
├── build_windows.bat / build_linux.sh   # PyInstaller 打包脚本
└── requirements.txt
```

## 自测

```bash
python tests/smoke.py    # 启动 mock 上游 + 网关，验证鉴权/调度/冷却/流式/信任路由
```

## License

[MIT](LICENSE)
