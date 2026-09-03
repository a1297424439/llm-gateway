"use strict";
/* ============ 视图函数 ============ */
const VIEWS = {
  dashboard() {
    const d = S.data, c = cfg();
    const url = (d.urls && d.urls[0] && d.urls[0].url) || "";
    const anthUrl = url.replace(/\/v1$/, "");
    const anthUrlLan = d.urls && d.urls[1] ? d.urls[1].url.replace(/\/v1$/, "") : "";
    const key = c.server.key || "";
    const st = d.stats || {};
    const cds = d.cooldowns || [];
    const up = fmtDur(d.uptime || 0);
    const enabledN = (c.providers || []).filter(p => p.enabled).length;
    const schedP = schedProviders();
    const rec = c.recommended_model || "auto";
    const demoModel = rec;

    return `
    <div class="banner fade-in" style="margin-bottom:16px">
      <div class="banner-inner" style="background:var(--orange-soft);color:var(--orange)"><span>数据无价：重要项目请使用安全路由（信任路由），仅经你标记为「可信」的渠道转发</span></div>
    </div>

    <div class="promo-banner fade-in">
      <div class="promo-inner">
        <span class="promo-icon">🔗</span>
        <div class="promo-text">
          <div class="promo-title">找更多中转站？</div>
          <div class="promo-desc">LLM Nav 收录优质 API 中转站，持续更新</div>
        </div>
        <button class="btn btn-sm promo-btn" data-act="open-promo">去看看</button>
      </div>
    </div>

    <div class="view-title fade-in">概览</div>
    <div class="card fade-in">
      <div class="row">
        <div class="row-main">
          <div class="label" style="display:flex;align-items:center;gap:8px">
            <span style="width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 0 3px var(--green-soft)"></span>
            服务运行中
          </div>
          <div class="desc">已运行 <span id="uptimeText">${up}</span></div>
        </div>
        <div class="segmented" style="min-width:220px">
          <button class="seg-btn ${c.mode !== "safe" ? "active" : ""}" data-act="mode-seg" data-mode="smart">智能路由</button>
          <button class="seg-btn ${c.mode === "safe" ? "active" : ""}" data-act="mode-seg" data-mode="safe">安全路由</button>
        </div>
      </div>
      <div class="row"><div class="desc">${modeDesc(c.mode)}</div></div>
      <div class="row">
        <div class="row-main"><div class="label">接口地址 — OpenAI 兼容</div><div class="desc">Cherry Studio / LobeChat / OpenWebUI 等绝大多数客户端</div></div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          <span class="url-pill"><span>${esc(url)}</span></span>
          ${d.urls.length > 1 ? `<span class="url-pill"><span>${esc(d.urls[1].url)}</span></span>` : ""}
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(url)}">复制</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">接口地址 — Anthropic 兼容</div><div class="desc">Claude Code / Claude 方言客户端（地址不带 /v1）</div></div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          <span class="url-pill"><span>${esc(anthUrl)}</span></span>
          ${d.urls.length > 1 ? `<span class="url-pill"><span>${esc(anthUrlLan)}</span></span>` : ""}
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(anthUrl)}">复制</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main">
          <div class="label">API Key</div>
          <div class="desc key-mask" id="keyText">${S.keyVisible ? esc(key) : esc(maskKey(key))}</div>
        </div>
        <div class="btn-row">
          <button class="btn btn-sm btn-plain" data-act="key-toggle">${S.keyVisible ? "隐藏" : "显示"}</button>
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(key)}">复制</button>
          <button class="btn btn-sm btn-danger" data-act="key-regen">重新生成</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main">
          <div class="label">调度模型名</div>
          <div class="desc">在智能体（Agent）中填写的模型名称</div>
        </div>
        <span class="url-pill" style="flex:none"><span>auto</span></span>
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">调度概览</div><div class="card-sub">每行一个渠道 · 上方优先调度 · 失败进入冷却池后自动降级${c.mode === "safe" ? "（安全路由：仅可信渠道）" : ""}</div></div></div>
      ${schedP.length ? schedP.map((p, i) => `
        <div class="cd-row">
          <span class="wl-order t${tierOf(p)}">${i + 1}</span>
          <div class="row-main">
            <div class="label">${esc(p.name)}</div>
            <div class="chips" style="padding:5px 0 0">
              ${(p.sched_models || []).map(m => `<span class="chip off" style="cursor:default">${esc(m)}${ctxBadge(p, m)}</span>`).join("")}
            </div>
          </div>
        </div>`).join("")
        : `<div class="empty">${c.mode === "safe" ? "安全路由下暂无可用渠道（请启用「可信」渠道并勾选模型）" : "尚未勾选任何模型 — 前往「渠道」页点击模型标签加入调度"}</div>`}
    </div>

    <div class="stats-grid fade-in">
      <div class="stat-card"><div class="stat-num" id="st-total">${st.total ?? 0}</div><div class="stat-label">总请求（近期）</div></div>
      <div class="stat-card"><div class="stat-num" id="st-rate">${st.success_rate ?? 100}%</div><div class="stat-label">成功率</div></div>
      <div class="stat-card"><div class="stat-num" id="st-cool" style="color:${cds.length ? "var(--orange)" : "inherit"}">${cds.length}</div><div class="stat-label">冷却中渠道·模型</div></div>
      <div class="stat-card"><div class="stat-num" id="st-prov">${enabledN}</div><div class="stat-label">启用渠道</div></div>
    </div>

    <div class="card fade-in">
      <div class="card-header">
        <div><div class="card-title">冷却池</div><div class="card-sub">失败模型按指数退避冷却，到期后半开重试</div></div>
        <span id="cdClearBtn">${cds.length ? '<button class="btn btn-sm btn-plain" data-act="cd-clear">全部恢复</button>' : ""}</span>
      </div>
      <div id="cdList">${cdListHtml(cds)}</div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">接入示例</div><div class="card-sub">任意 OpenAI 兼容客户端（Cherry Studio / LobeChat / OpenWebUI / Hermes…）</div></div></div>
      <div class="card-pad" style="padding-top:0">
        <div class="row" style="border:none;padding:0 0 10px"><span class="badge badge-gray">API 地址</span><span class="mono">${esc(url)}</span></div>
        <div class="row" style="border:none;padding:0 0 12px"><span class="badge badge-gray">API Key</span><span class="mono">${esc(maskKey(key))}</span></div>
        <div class="row" style="border:none;padding:0 0 12px"><span class="badge badge-gray">模型名</span><span class="mono">${esc(demoModel)}</span> <span class="hint">（勾选的模型名任填一个）</span></div>
        <div class="code" id="curlBlock">${esc(buildCurl(url, key, demoModel))}</div>
        <div style="margin-top:10px;display:flex;gap:8px">
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(buildCurl(url, key, demoModel))}">复制示例</button>
          <button class="btn btn-sm btn-plain" data-act="nav" data-view="providers">去勾选模型</button>
        </div>
      </div>
    </div>`;
  },

  providers() {
    const c = cfg();
    const sorted = [...(c.providers || [])].sort((a, b) =>
      (a.priority || 99) - (b.priority || 99) || String(a.name || "").localeCompare(String(b.name || "")));
    const safeHint = c.mode === "safe"
      ? `<div class="banner"><div class="banner-inner" style="background:var(--green-soft);color:var(--green)"><span>安全路由已开启：仅你标记为「可信」的渠道参与调度</span></div></div>` : "";
    const tiers = [
      { name: "一档 · 优先调度", desc: "最上面的最先调度；免费/公益放这里", range: "优先级 1~9", empty: "把渠道卡片拖到这里即可进入一档" },
      { name: "二档 · 稳定承接", desc: "一档全部冷却时由这一档顶上", range: "优先级 10~19", empty: "把渠道卡片拖到这里即可进入二档" },
      { name: "三档 · 官方兜底", desc: "最后防线，保证始终有可用出口", range: "优先级 20+", empty: "把渠道卡片拖到这里即可进入三档" },
    ];
    const sections = tiers.map((t, ti) => {
      const ps = sorted.filter(p => tierOf(p) === ti);
      const models = ps.reduce((n, p) => n + (p.enabled ? (p.sched_models || []).length : 0), 0);
      const collapsed = S.collapsedTiers.includes(ti);
      return `
      <div class="tier-section ${t.cls || ''}" data-tier="${ti}">
        <button class="tier-head" data-act="tier-collapse" data-ti="${ti}" title="${collapsed ? "展开" : "折叠"}">
          <span class="chev">${collapsed ? "▸" : "▾"}</span>
          <span>${t.name}</span>
          ${collapsed ? "" : `<span class="sub">${t.desc}</span>`}
          <span class="sub" style="margin-left:auto;white-space:nowrap">${t.range} · ${ps.length} 渠道 · ${models} 模型</span>
        </button>
        ${collapsed ? "" : (ps.length ? ps.map(p => providerCard(p, ti)).join("")
          : `<div class="tier-empty">${t.empty}</div>`)}
      </div>`;
    }).join("");
    return `
    <div class="view-title fade-in">渠道
      <button class="btn btn-primary" data-act="provider-add">＋ 添加渠道</button>
    </div>
    ${safeHint}
    <div class="card card-pad fade-in hint" style="margin-bottom:14px">
      <b>拖拽渠道卡片</b>调整调度顺序：<b>越靠上越优先</b>，拖入对应档位即可自动归类。
      点击模型标签勾选参与调度（高亮 ✓），<b>勾选后拖拽标签</b>可调整该渠道内的调度顺序；
      失败自动进入冷却池并降级到下一档；同名模型多渠道勾选即自动互备。
    </div>
    <div class="card fade-in" style="margin-bottom:14px">
      <div class="row">
        <div class="row-main"><div class="desc">点击模型标签勾选参与调度；标签上的 K 数 = 上下文长度（~ 为家族推测，? 为未知）。勾选后拖拽标签可调顺序。</div></div>
      </div>
    </div>
    ${sorted.length ? sections : `<div class="card fade-in"><div class="empty"><div class="big">暂无渠道</div>点击右上角「添加渠道」，可从预设一键填充 DeepSeek、智谱、Kimi 等</div></div>`}`;
  },

  settings() {
    const c = cfg();
    const r = c.routing || {}, cd = c.cooldown || {}, sv = c.server || {};
    return `
    <div class="view-title fade-in">设置</div>

    <div class="card fade-in sponsor-card">
      <div class="card-header">
        <div><div class="card-title">支持这个项目</div><div class="card-sub">如果调度中枢对你有帮助，欢迎请作者喝杯咖啡</div></div>
      </div>
      <div class="card-pad" style="padding-top:0;text-align:center">
        <img src="/sponsor-qr.png" alt="Sponsor QR" style="width:140px;height:140px;border-radius:12px">
        <div class="hint" style="margin-top:8px">感谢义父义母赞助，作者跪谢 🙏</div>
        <div style="margin-top:12px;display:flex;gap:8px;justify-content:center">
          <button class="btn btn-sm btn-plain" data-act="sponsor-copy" data-copy="your-payment-link-here">复制赞助链接</button>
          <button class="btn btn-sm btn-plain" data-act="sponsor-open">打开赞助页</button>
        </div>
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">调度参数</div><div class="card-sub">调度模式在「概览」页顶部切换</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">最大尝试次数</div><div class="desc">单次请求最多尝试的候选渠道数量</div></div>
        <input type="number" min="1" max="10" value="${r.max_attempts ?? 4}" data-change="settings-num" data-sect="routing" data-field="max_attempts">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">上游超时（秒）</div><div class="desc">连接与流式读取的整体兜底超时</div></div>
        <input type="number" min="10" max="600" value="${r.timeout_seconds ?? 120}" data-change="settings-num" data-sect="routing" data-field="timeout_seconds">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">模型响应超时（秒）</div><div class="desc">单个模型超过此时间未响应即跳过、进冷却换下一个；默认 90 秒覆盖 99% 正常响应（实测 p95≈38s）</div></div>
        <input type="number" min="10" max="600" value="${r.model_timeout_seconds ?? 90}" data-change="settings-num" data-sect="routing" data-field="model_timeout_seconds">
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">冷却池</div><div class="card-sub">模型级：失败按 base × 2ⁿ 退避，封顶 max；渠道级：额度类错误触发，5 小时起步封顶 7 天</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">基础冷却（秒）</div></div>
        <input type="number" min="5" max="3600" value="${cd.base_seconds ?? 60}" data-change="settings-num" data-sect="cooldown" data-field="base_seconds">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">最大冷却（秒）</div></div>
        <input type="number" min="30" max="86400" value="${cd.max_seconds ?? 1800}" data-change="settings-num" data-sect="cooldown" data-field="max_seconds">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">渠道冷却基础（秒）</div><div class="desc">额度类错误（402、余额不足等）触发，整个渠道被跳过：18000 = 5 小时</div></div>
        <input type="number" min="300" max="604800" value="${cd.provider_base_seconds ?? 18000}" data-change="settings-num" data-sect="cooldown" data-field="provider_base_seconds">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">渠道冷却最大（秒）</div><div class="desc">604800 = 7 天；渠道内任一请求成功即自动解除渠道冷却</div></div>
        <input type="number" min="600" max="1209600" value="${cd.provider_max_seconds ?? 604800}" data-change="settings-num" data-sect="cooldown" data-field="provider_max_seconds">
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">服务器</div><div class="card-sub">配置文件：${esc(S.data.config_path)}</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">监听范围</div><div class="desc">${sv.host === "0.0.0.0" ? "局域网可访问（" + esc(S.data.lan_ip || "") + "）" : "仅本机 127.0.0.1 可访问"}</div></div>
        <div class="segmented" style="max-width:260px">
          <button class="seg-btn ${sv.host !== "0.0.0.0" ? "active" : ""}" data-act="host-seg" data-host="127.0.0.1">仅本机</button>
          <button class="seg-btn ${sv.host === "0.0.0.0" ? "active" : ""}" data-act="host-seg" data-host="0.0.0.0">局域网</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">端口</div><div class="desc">默认随机生成并固定保存；可手动修改（1–65535），改完需重启生效</div></div>
        <div class="btn-row">
          <input type="number" min="1" max="65535" value="${sv.port ?? ""}" style="width:100px;text-align:center" data-change="settings-port" placeholder="端口">
          <button class="btn btn-sm btn-plain" data-act="port-regen">随机</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">API Key</div><div class="desc key-mask">${esc(maskKey(sv.key || ""))}（首次生成后固定，重启不变）</div></div>
        <button class="btn btn-sm btn-danger" data-act="key-regen">重新生成</button>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">点 ✕ 时</div><div class="desc">关闭窗口按钮的行为（Hermes 等客户端只有在程序运行时才能连接）</div></div>
        <div class="segmented" style="max-width:330px">
          ${[["", "每次询问"], ["hide", "隐藏到托盘"], ["quit", "退出程序"]].map(([v, t]) =>
            `<button class="seg-btn ${(c.server.close_action || "") === v ? "active" : ""}" data-act="close-seg" data-v="${v}">${t}</button>`).join("")}
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">开机自启</div><div class="desc">登录系统后自动在后台启动网关（无界面模式，地址与 Key 不变）</div></div>
        <label class="switch"><input type="checkbox" data-change="autostart" ${S.autostart ? "checked" : ""}><span class="knob"></span></label>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">关于</div><div class="desc">当前版本 <span class="mono">${esc(S.data.version || "")}</span><span id="updateHint"></span></div></div>
        <div class="btn-row">
          <button class="btn btn-sm btn-plain" data-act="check-update">检查更新</button>
          <button class="btn btn-sm btn-plain" id="applyUpdateBtn" data-act="apply-update" style="display:none">立即更新</button>
        </div>
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">外观与数据</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">主题</div></div>
        <div class="segmented" style="max-width:240px">
          <button class="seg-btn ${S.theme === "auto" ? "active" : ""}" data-act="theme-set" data-theme="auto">自动</button>
          <button class="seg-btn ${S.theme === "light" ? "active" : ""}" data-act="theme-set" data-theme="light">浅色</button>
          <button class="seg-btn ${S.theme === "dark" ? "active" : ""}" data-act="theme-set" data-theme="dark">深色</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">配置备份</div><div class="desc">导出/导入全部渠道与设置（含密钥，注意保管）</div></div>
        <div class="btn-row">
          <button class="btn btn-sm btn-plain" data-act="cfg-export">导出</button>
          <button class="btn btn-sm btn-plain" data-act="cfg-import">导入</button>
          <input type="file" id="import-file" accept=".json" style="display:none">
        </div>
      </div>
    </div>`;
  },

  logs() {
    return `
    <div class="view-title fade-in">请求日志
      <div class="btn-row">
        <div class="segmented" style="max-width:240px">
          ${["all", "ok", "fail"].map(f => `<button class="seg-btn ${S.logFilter === f ? "active" : ""}" data-act="log-filter" data-f="${f}">${{ all: "全部", ok: "成功", fail: "失败" }[f]}</button>`).join("")}
        </div>
        <button class="btn btn-sm btn-plain" data-act="logs-clear">清空</button>
        <button class="btn btn-sm btn-plain" data-act="logs-export">导出</button>
      </div>
    </div>
    <div class="card fade-in"><div id="logList">${logListHtml()}</div></div>`;
  },
};


