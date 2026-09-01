# LLM 智能调度网关

一个跑在本地的**大模型 API 智能调度器 / 网关**。它把不同网站的 API 统一成一个
OpenAI 兼容接口，带 iOS 风格管理面板，支持多渠道接入、别名映射、智能/安全双路由、
优先级调度、冷却池故障转移，Windows / Linux 通用。

```
客户端(Cherry Studio/LobeChat/OpenWebUI/任意SDK)
        │  http://127.0.0.1:<随机端口>/v1  + 本地随机 Key
        ▼
┌─────────────────────────────┐
│      LLM 智能调度网关        │
│  智能路由 / 安全路由 / 冷却池 │
└─────────────────────────────┘
   │         │         │        ───→ DeepSeek / 智谱 / Kimi / 百炼 / 硅基流动 …
   │         │         └──────────→ OpenAI / Anthropic / Gemini / OpenRouter …
```

## 功能特性

- **多渠道同时接入**：可添加任意多个网站的 API，OpenAI 兼容协议直接可用，
  Anthropic 原生协议自动转换（消息格式、流式、工具调用双向翻译）。
- **统一别名映射**：不同网站的模型名各不相同但往往是同一款模型。给它们起一个
  统一别名，客户端只请求别名；别名输入框支持从历史别名下拉选取或输入新名称，
  下次直接选用。
- **双路由模式**
  - 智能路由：全部启用渠道参与调度；
  - 安全路由：**只允许调度你标记为「可信」的渠道**（预设中 DeepSeek、智谱、Kimi、
    百炼、硅基流动、火山方舟等默认标记为可信，可在渠道设置中调整）。
- **智能路由调度**
  - 网站优先 / 模型优先两种策略（分段开关一键切换）；
  - 模型白名单：只有白名单内别名可被调用，顺序即优先级，支持「白名单回退」；
  - 冷却池：上游失败自动进入冷却池（指数退避 `base×2ⁿ` 封顶，429 优先尊重
    `Retry-After`），继续调度下一优先级；到期后半开重试，成功即恢复；
  - 单次请求最多尝试 N 个候选（可配置），首个 token 返回前均可故障转移。
- **随机本地地址与 Key**：首次启动自动生成随机监听端口与 `sk-lg-` 随机密钥，
  重新生成的 Key 保证与历史不重复；面板可一键重新生成/更换端口。
- **iOS 审美面板**：毛玻璃卡片、iOS 开关与分段控件、浅色/深色/跟随系统主题、
  底部浮动 Tab 栏；概览 / 渠道 / 模型 / 路由 / 日志 五个页面。
- 其他：连通性测试与在线获取模型列表、请求日志与成功统计、配置导出/导入、
  流式(SSE)透传、embeddings 透传。

## 快速开始

### 桌面软件形态

`python main.py`（或双击 `dist\llm-gateway.exe`）默认**直接弹出一个原生桌面窗口**
承载管理面板（Windows 使用系统自带 WebView2 渲染，Linux 使用 WebKitGTK），
带标准标题栏与任务栏图标，**关闭窗口即退出服务**。

```bash
python main.py             # 桌面窗口模式（默认）
python main.py --browser   # 不弹窗口，直接在默认浏览器打开面板
python main.py --no-ui     # 无界面服务模式，后台常驻（Ctrl+C 停止）
```

桌面窗口依赖：Windows 10/11 自带 WebView2 运行时；Linux 需安装 WebKitGTK
（Debian/Ubuntu: `sudo apt install libwebkit2gtk-4.1-dev`）。环境缺失时程序会
自动回退到浏览器打开面板，不影响功能。

### 源码运行（Windows / Linux / macOS，需 Python 3.9+）

```bash
cd llm-gateway
pip install -r requirements.txt pywebview
python main.py
```

启动后控制台会打印：

```
  管理面板 : http://127.0.0.1:38127/
  接口地址 : http://127.0.0.1:38127/v1  (OpenAI 兼容)
  API Key  : sk-lg-xxxxxxxx...
```

浏览器打开管理面板 → 「渠道」页添加 API → 「模型」页建立别名映射 → 复制
接口地址和 Key 填进任意 OpenAI 兼容客户端即可。

### 打包成单文件可执行程序

```bash
# Windows（双击 build_windows.bat 或命令行执行）
build_windows.bat        # 产出 dist\llm-gateway.exe

# Linux
chmod +x build_linux.sh && ./build_linux.sh   # 产出 dist/llm-gateway
```

可执行文件首次运行同样会生成随机端口/Key 并打印面板地址；数据文件与脚本同机存放。

## 使用指南

1. **添加渠道**：「渠道」页 → 添加渠道 → 从预设选择（自动填充 Base URL、协议、
   可信标记）→ 填入 API Key → 保存后点「获取模型列表 / 测试连通」。
2. **建立映射**：「模型」页 → 新建别名（如 `deepseek-chat`）→ 添加多条映射，
   每条映射选择 渠道 + 上游模型名 + 优先级（数字越小越优先）。也可以直接在渠道页
   点击模型名小标签快速映射。另一个便捷入口：渠道卡片的「模型名」标签点击即可映射到别名。
3. **白名单**（可选）：「模型」页底部开启白名单，把别名按优先级排序加入；
   「白名单回退」开启后，客户端请求任何未知模型名都会按白名单顺序调度。
4. **选择模式与策略**：「路由」页切换 智能路由/安全路由、网站优先/模型优先、
   调整尝试次数/超时/冷却参数。
5. **接入客户端**：API 地址 `http://127.0.0.1:端口/v1`，API Key 即面板显示的
   `sk-lg-...`。

### 路由排序规则

| 策略 | 排序键（从小到大依次比较） |
|------|---------------------------|
| 网站优先 | 渠道优先级 → 映射条目优先级 → 渠道名 |
| 模型优先 | 映射条目优先级 → 渠道优先级 → 渠道名 |

安全路由会在排序前过滤掉所有未标记「可信」的渠道；冷却中的候选直接跳过；
渠道返回 401/403 时本次请求跳过该渠道其余模型（密钥错误不该反复重试）。

## API

与 OpenAI 完全兼容，支持 `stream: true`（SSE）：

```bash
curl http://127.0.0.1:38127/v1/chat/completions \
  -H "Authorization: Bearer sk-lg-xxxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"你好"}]}'
```

- `GET  /v1/models` — 别名列表（安全模式/白名单会过滤）
- `POST /v1/chat/completions` — 对话补全（流式/非流式）
- `POST /v1/embeddings` — 向量（OpenAI 兼容渠道）
- `GET  /health` — 健康检查（免鉴权）

## 数据与配置

- 配置：`%APPDATA%\LLMGateway\config.json`（Windows）；
  `~/.config/llm-gateway/config.json`（Linux）。
- 运行状态（日志/冷却池）：同目录 `state.json`。
- 便携模式：设置环境变量 `LLM_GATEWAY_HOME` 指向任意目录。
- 「路由」页支持配置导出/导入（JSON，含密钥，注意保管）。

## 常见问题

- **端口被占用？** 启动时会自动等待/改用新的随机端口；也可在面板「随机更换」后重启。
- **修改监听范围（局域网）后不生效？** 端口/监听地址修改需要重启程序（面板有一键重启）。
- **预设 Base URL 失效？** 服务商可能调整地址，以各家官方文档为准，渠道支持自定义 URL。
- **Anthropic 渠道**：适配器为「Anthropic 原生」时走 `api.anthropic.com/v1/messages`
  并自动做协议互转；工具调用为尽力转换，图片仅支持 base64。
- **安全提示**：面板与网关默认只监听本机；管理接口在本机免鉴权，若开启局域网监听，
  建议在「非本机」访问面板时输入网关 Key（面板会自动要求），不要将端口暴露到公网。

## 项目结构

```
llm-gateway/
├── main.py              # 入口（随机端口/Key、重启宽限、启动横幅）
├── app/
│   ├── config.py        # 配置持久化、随机 Key/端口生成（历史去重）
│   ├── state.py         # 请求日志、冷却池（指数退避）、统计
│   ├── router.py        # 调度：网站/模型优先、白名单、安全模式过滤
│   ├── adapters.py      # OpenAI 兼容 / Anthropic 原生互转、SSE 解析
│   ├── server.py        # FastAPI：/v1 网关 + /api 面板接口 + 静态页
│   ├── presets.py       # 常见服务商预设（可信标记）
├── web/                 # iOS 风格前端（原生 HTML/CSS/JS，无构建步骤）
├── tests/
│   ├── mock_upstream.py # 本地 mock 上游（自测/体验用）
│   └── smoke.py         # 端到端冒烟测试（17 项断言）
├── build_windows.bat / build_linux.sh   # PyInstaller 打包脚本
└── requirements.txt
```

## 自测

```bash
python tests/smoke.py    # 启动 mock 上游 + 网关，验证鉴权/路由/冷却/流式/安全模式/白名单
```
