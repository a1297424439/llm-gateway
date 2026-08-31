# LLM Gateway · Smart LLM Dispatcher

**English | [简体中文](README.md)**

A local **LLM API dispatcher / gateway** that unifies multiple website/subscription LLM
APIs into a single OpenAI-compatible endpoint. Automatic priority-based failover, iOS-style
management panel. Windows / Linux.

> **Why this?** Most LLM gateways assume pay-per-use API keys as upstream. But many people
> use **subscription-based relay sites** (monthly/quota sites) — once quota is exhausted,
> requests hit 502. LLM Gateway is built for that: it detects "quota exhausted" errors, cools
> down the entire provider for hours, and fails over to the next available one.

```
Clients (Cherry Studio / LobeChat / OpenWebUI / any SDK / Agent)
        │  http://127.0.0.1:<port>/v1  +  local random Key
        ▼
┌──────────────────────────────┐
│        LLM Gateway           │
│  Smart / Trusted Routing     │
└──────────────────────────────┘
   │         │         └──→ provider 3 (fallback)
   │         └────────────→ provider 2
   └──────────────────────→ provider 1 (priority)
```

## Features

- **Multi-provider** : add any number of OpenAI-compatible APIs; Anthropic native protocol
  auto-converted both ways (messages, streaming, tool calls).
- **Direct model-name dispatch** : clients request upstream model names directly; providers
  that have the model scheduled are tried by tier. Same-named models across providers
  auto-mirror. Virtual model `auto` iterates all scheduled models by tier.
- **Dual routing modes**
  - Smart routing : all enabled providers participate.
  - Trusted routing (safe) : **only dispatch providers you marked "trusted"** — you decide who to trust.
- **Double-layer cooldown pool**
  - Model-level : exponential backoff `base × 2ⁿ`, capped at max, half-open retry on expiry.
  - Provider-level : quota errors (402 / insufficient balance / free quota exhausted) skip the
    whole provider, 5h start capped at 7 days; rate-limit (429) 60s start capped at 10 min.
- **Uninterrupted failover** : `max_attempts` counts *providers*, so all models within a
  provider are tried before falling over.
- **Bilingual UI** : Chinese / English auto-detect (follows system language, switchable in settings).
- **iOS-style panel** : frosted glass, light/dark/system theme, bottom tab bar
  (Overview / Providers / Settings / Logs).
- **Random local address & key** : random port and `sk-lg-` key generated on first run.
- Others : connectivity test & model list fetch, request logs & stats, config export/import,
  streaming (SSE) passthrough, embeddings passthrough, launch at login, LAN listen.

## Quick Start

### Desktop app

```bash
python main.py             # desktop window (default)
python main.py --browser   # open panel in browser instead
python main.py --no-ui     # headless service mode (Ctrl+C to stop)
```

Windows 10/11 ships WebView2; Linux needs WebKitGTK (`sudo apt install libwebkit2gtk-4.1-dev`).
Falls back to browser automatically if missing.

### Run from source (Python 3.9+)

```bash
cd llm-gateway
pip install -r requirements.txt pywebview
python main.py
```

### Build a single binary

```bash
build_windows.bat                      # Windows → dist\llm-gateway.exe
chmod +x build_linux.sh && ./build_linux.sh   # Linux → dist/llm-gateway
```

## Usage

1. **Add a provider** : Providers page → Add → fill from preset (auto Base URL / protocol /
   trusted flag) → paste API Key → Save → "Fetch models / Test connectivity".
2. **Schedule models** : click model chips in the provider card (highlighted ✓) to include in
   dispatch; drag cards/chips to reorder tiers (higher = higher priority).
3. **Choose routing mode** : toggle Smart / Trusted at the top of Overview.
4. **Plug into a client** : API base `http://127.0.0.1:<port>/v1`, model = upstream name or
   `auto`, key = the `sk-lg-...` shown in the panel.

## API

OpenAI-compatible, supports `stream: true` (SSE):

```bash
curl http://127.0.0.1:<port>/v1/chat/completions \
  -H "Authorization: Bearer <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello"}]}'
```

- `GET  /v1/models` — model list (auto + union of scheduled)
- `POST /v1/chat/completions` — chat completion (streaming / non-streaming)
- `POST /v1/embeddings` — embeddings (OpenAI-compatible providers)
- `POST /v1/messages` — Anthropic Messages protocol (Claude-dialect clients)
- `GET  /health` — health check (no auth)

## Data & Config

- Config : `%APPDATA%\LLMGateway\config.json` (Windows) / `~/.config/llm-gateway/config.json` (Linux)
- State (logs/cooldown pool) : same dir `state.json`
- Portable mode : set `LLM_GATEWAY_HOME` env var to any directory
- Settings page supports config export/import (JSON, includes secrets — keep it safe)

## FAQ

- **Port in use?** Auto-waits/uses a new random port; regenerate in panel then restart.
- **LAN listen not taking effect?** Port/address change needs a restart (one-click in panel).
- **Security** : listens on localhost by default; if enabling LAN, enter the key when accessing
  from other machines; do not expose to public internet.
- **Preset Base URL stale?** Providers may change URLs — the channel supports custom URLs.

## Project structure

```
llm-gateway/
├── main.py              # entry (random port/key, restart grace, startup banner)
├── app/
│   ├── config.py        # config persistence, random key/port generation
│   ├── state.py         # request logs, double-layer cooldown pool, stats
│   ├── router.py        # dispatch: tier priority, trusted-routing filter
│   ├── adapters.py      # OpenAI/Anthropic conversion, SSE, error classification
│   ├── server.py        # FastAPI: /v1 gateway + /api panel endpoints + static
│   └── presets.py       # common provider presets (trusted flag)
├── web/                 # vanilla HTML/CSS/JS frontend (i18n bilingual)
├── tests/               # mock upstream + end-to-end smoke tests
├── build_windows.bat / build_linux.sh   # PyInstaller build scripts
└── requirements.txt
```

## Self-test

```bash
python tests/smoke.py    # starts mock upstream + gateway; verifies auth/dispatch/cooldown/streaming/trusted routing
```

## License

[MIT](LICENSE)
