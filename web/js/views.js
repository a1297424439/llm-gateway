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
      <div class="banner-inner" style="background:var(--orange-soft);color:var(--orange)"><span>${t("banner_data")}</span></div>
    </div>

    <div class="promo-banner fade-in">
      <div class="promo-inner">
        <span class="promo-icon">🔗</span>
        <div class="promo-text">
          <div class="promo-title">${t("promo_title")}</div>
          <div class="promo-desc">${t("promo_desc")}</div>
        </div>
        <button class="btn btn-sm promo-btn" data-act="open-promo">${t("promo_go")}</button>
      </div>
    </div>

    <div class="view-title fade-in">${t("view_title_dash")}</div>
    <div class="card fade-in">
      <div class="row">
        <div class="row-main">
          <div class="label" style="display:flex;align-items:center;gap:8px">
            <span style="width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 0 3px var(--green-soft)"></span>
            ${t("running")}
          </div>
          <div class="desc">${t("uptime")} <span id="uptimeText">${up}</span></div>
        </div>
        <div class="segmented" style="min-width:220px">
          <button class="seg-btn ${c.mode !== "safe" ? "active" : ""}" data-act="mode-seg" data-mode="smart">${t("mode_smart")}</button>
          <button class="seg-btn ${c.mode === "safe" ? "active" : ""}" data-act="mode-seg" data-mode="safe">${t("mode_safe")}</button>
        </div>
      </div>
      <div class="row"><div class="desc">${modeDesc(c.mode)}</div></div>
      <div class="row">
        <div class="row-main"><div class="label">${t("endpoint_openai")}</div><div class="desc">${t("endpoint_openai_desc")}</div></div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          <span class="url-pill"><span>${esc(url)}</span></span>
          ${d.urls.length > 1 ? `<span class="url-pill"><span>${esc(d.urls[1].url)}</span></span>` : ""}
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(url)}">${t("common_copy")}</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("endpoint_anth")}</div><div class="desc">${t("endpoint_anth_desc")}</div></div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          <span class="url-pill"><span>${esc(anthUrl)}</span></span>
          ${d.urls.length > 1 ? `<span class="url-pill"><span>${esc(anthUrlLan)}</span></span>` : ""}
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(anthUrl)}">${t("common_copy")}</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main">
          <div class="label">${t("api_key_label")}</div>
          <div class="desc key-mask" id="keyText">${S.keyVisible ? esc(key) : esc(maskKey(key))}</div>
        </div>
        <div class="btn-row">
          <button class="btn btn-sm btn-plain" data-act="key-toggle">${S.keyVisible ? t("common_hide") : t("common_show")}</button>
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(key)}">${t("common_copy")}</button>
          <button class="btn btn-sm btn-danger" data-act="key-regen">${t("server_regen_key")}</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main">
          <div class="label">${t("sched_model_name")}</div>
          <div class="desc">${t("sched_model_desc")}</div>
        </div>
        <span class="url-pill" style="flex:none"><span>auto</span></span>
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">${t("sched_overview")}</div><div class="card-sub">${t("sched_overview_sub")}${c.mode === "safe" ? t("sched_safe_sub") : ""}</div></div></div>
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
        : `<div class="empty">${c.mode === "safe" ? t("sched_empty_safe") : t("sched_empty_none")}</div>`}
    </div>

    <div class="stats-grid fade-in">
      <div class="stat-card"><div class="stat-num" id="st-total">${st.total ?? 0}</div><div class="stat-label">${t("stat_total")}</div></div>
      <div class="stat-card"><div class="stat-num" id="st-rate">${st.success_rate ?? 100}%</div><div class="stat-label">${t("stat_rate")}</div></div>
      <div class="stat-card"><div class="stat-num" id="st-cool" style="color:${cds.length ? "var(--orange)" : "inherit"}">${cds.length}</div><div class="stat-label">${t("stat_cool")}</div></div>
      <div class="stat-card"><div class="stat-num" id="st-prov">${enabledN}</div><div class="stat-label">${t("stat_enabled")}</div></div>
    </div>

    <div class="card fade-in">
      <div class="card-header">
        <div><div class="card-title">${t("cd_pool")}</div><div class="card-sub">${t("cd_pool_sub")}</div></div>
        <span id="cdClearBtn">${cds.length ? `<button class="btn btn-sm btn-plain" data-act="cd-clear">${t("cd_clear_all")}</button>` : ""}</span>
      </div>
      <div id="cdList">${cdListHtml(cds)}</div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">${t("example_title")}</div><div class="card-sub">${t("example_sub")}</div></div></div>
      <div class="card-pad" style="padding-top:0">
        <div class="row" style="border:none;padding:0 0 10px"><span class="badge badge-gray">${t("endpoint_model")}</span><span class="mono">${esc(url)}</span></div>
        <div class="row" style="border:none;padding:0 0 12px"><span class="badge badge-gray">${t("api_key_label")}</span><span class="mono">${esc(maskKey(key))}</span></div>
        <div class="row" style="border:none;padding:0 0 12px"><span class="badge badge-gray">${t("model_name_badge")}</span><span class="mono">${esc(demoModel)}</span> <span class="hint">${t("endpoint_model_note")}</span></div>
        <div class="code" id="curlBlock">${esc(buildCurl(url, key, demoModel))}</div>
        <div style="margin-top:10px;display:flex;gap:8px">
          <button class="btn btn-sm btn-plain" data-act="copy" data-copy="${esc(buildCurl(url, key, demoModel))}">${t("example_copy")}</button>
          <button class="btn btn-sm btn-plain" data-act="nav" data-view="providers">${t("example_select")}</button>
        </div>
      </div>
    </div>`;
  },

  providers() {
    const c = cfg();
    const sorted = [...(c.providers || [])].sort((a, b) =>
      (a.priority || 99) - (b.priority || 99) || String(a.name || "").localeCompare(String(b.name || "")));
    const safeHint = c.mode === "safe"
      ? `<div class="banner"><div class="banner-inner" style="background:var(--green-soft);color:var(--green)"><span>${t("safe_banner")}</span></div></div>` : "";
    const tiers = [
      { name: t("tier1_name"), desc: t("tier1_desc"), range: t("tier1_range"), empty: t("tier1_empty") },
      { name: t("tier2_name"), desc: t("tier2_desc"), range: t("tier2_range"), empty: t("tier2_empty") },
      { name: t("tier3_name"), desc: t("tier3_desc"), range: t("tier3_range"), empty: t("tier3_empty") },
    ];
    const sections = tiers.map((tier, ti) => {
      const ps = sorted.filter(p => tierOf(p) === ti);
      const models = ps.reduce((n, p) => n + (p.enabled ? (p.sched_models || []).length : 0), 0);
      const collapsed = S.collapsedTiers.includes(ti);
      return `
      <div class="tier-section ${tier.cls || ''}" data-tier="${ti}">
        <button class="tier-head" data-act="tier-collapse" data-ti="${ti}" title="${collapsed ? t("common_expand") : t("common_collapse")}">
          <span class="chev">${collapsed ? "▸" : "▾"}</span>
          <span>${tier.name}</span>
          ${collapsed ? "" : `<span class="sub">${tier.desc}</span>`}
          <span class="sub" style="margin-left:auto;white-space:nowrap">${tier.range} · ${ps.length} ${t("tier_channel")} · ${models} ${t("tier_model")}</span>
        </button>
        ${collapsed ? "" : (ps.length ? ps.map(p => providerCard(p, ti)).join("")
          : `<div class="tier-empty">${tier.empty}</div>`)}
      </div>`;
    }).join("");
    return `
    <div class="view-title fade-in">${t("view_title_prov")}
      <button class="btn btn-primary" data-act="provider-add">${t("p_add_btn")}</button>
    </div>
    ${safeHint}
    <div class="card card-pad fade-in hint" style="margin-bottom:14px">
      ${t("prov_drag_hint")}
    </div>
    <div class="card fade-in" style="margin-bottom:14px">
      <div class="row">
        <div class="row-main"><div class="desc">${t("prov_chip_hint")}</div></div>
      </div>
    </div>
    ${sorted.length ? sections : `<div class="card fade-in"><div class="empty"><div class="big">${t("prov_empty_big")}</div>${t("prov_empty_hint")}</div></div>`}`;
  },

  settings() {
    const c = cfg();
    const r = c.routing || {}, cd = c.cooldown || {}, sv = c.server || {};
    return `
    <div class="view-title fade-in">${t("view_title_settings")}</div>

    <div class="card fade-in sponsor-card">
      <div class="card-header">
        <div><div class="card-title">${t("sponsor_title")}</div><div class="card-sub">${t("sponsor_sub")}</div></div>
      </div>
      <div class="card-pad" style="padding-top:0;text-align:center">
        <img src="/sponsor-qr.png" alt="Sponsor QR" style="width:140px;height:140px;border-radius:12px">
        <div class="hint" style="margin-top:8px">${t("sponsor_qr_hint")}</div>
        <div style="margin-top:12px;display:flex;gap:8px;justify-content:center">
          <button class="btn btn-sm btn-plain" data-act="sponsor-copy" data-copy="your-payment-link-here">${t("sponsor_copy")}</button>
          <button class="btn btn-sm btn-plain" data-act="sponsor-open">${t("sponsor_open")}</button>
        </div>
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">${t("routing_params")}</div><div class="card-sub">${t("routing_params_sub")}</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">${t("max_attempts")}</div><div class="desc">${t("max_attempts_desc")}</div></div>
        <input type="number" min="1" max="10" value="${r.max_attempts ?? 4}" data-change="settings-num" data-sect="routing" data-field="max_attempts">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("upstream_timeout")}</div><div class="desc">${t("upstream_timeout_desc")}</div></div>
        <input type="number" min="10" max="600" value="${r.timeout_seconds ?? 120}" data-change="settings-num" data-sect="routing" data-field="timeout_seconds">
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">${t("cd_pool")}</div><div class="card-sub">${t("cd_pool_params_sub")}</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">${t("cd_base")}</div></div>
        <input type="number" min="5" max="3600" value="${cd.base_seconds ?? 60}" data-change="settings-num" data-sect="cooldown" data-field="base_seconds">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("cd_max")}</div></div>
        <input type="number" min="30" max="86400" value="${cd.max_seconds ?? 1800}" data-change="settings-num" data-sect="cooldown" data-field="max_seconds">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("cd_provider_base")}</div><div class="desc">${t("cd_provider_base_desc")}</div></div>
        <input type="number" min="300" max="604800" value="${cd.provider_base_seconds ?? 18000}" data-change="settings-num" data-sect="cooldown" data-field="provider_base_seconds">
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("cd_provider_max")}</div><div class="desc">${t("cd_provider_max_desc")}</div></div>
        <input type="number" min="600" max="1209600" value="${cd.provider_max_seconds ?? 604800}" data-change="settings-num" data-sect="cooldown" data-field="provider_max_seconds">
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">${t("server_card")}</div><div class="card-sub">${t("config_path_label")}：${esc(S.data.config_path)}</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">${t("server_scope")}</div><div class="desc">${sv.host === "0.0.0.0" ? t("server_lan", { ip: esc(S.data.lan_ip || "") }) : t("server_local")}</div></div>
        <div class="segmented" style="max-width:260px">
          <button class="seg-btn ${sv.host !== "0.0.0.0" ? "active" : ""}" data-act="host-seg" data-host="127.0.0.1">${t("server_local_only")}</button>
          <button class="seg-btn ${sv.host === "0.0.0.0" ? "active" : ""}" data-act="host-seg" data-host="0.0.0.0">${t("server_lan_only")}</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("server_port")}</div><div class="desc">${t("server_port_desc")}</div></div>
        <div class="btn-row">
          <input type="number" min="1" max="65535" value="${sv.port ?? ""}" style="width:100px;text-align:center" data-change="settings-port" placeholder="${t("server_port_ph")}">
          <button class="btn btn-sm btn-plain" data-act="port-regen">${t("server_port_random")}</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("api_key_label")}</div><div class="desc key-mask">${esc(maskKey(sv.key || ""))}${t("server_key_desc")}</div></div>
        <button class="btn btn-sm btn-danger" data-act="key-regen">${t("server_regen_key")}</button>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("server_close")}</div><div class="desc">${t("server_close_desc")}</div></div>
        <div class="segmented" style="max-width:330px">
          ${[["", t("close_ask")], ["hide", t("close_hide_tray")], ["quit", t("close_quit_app")]].map(([v, label]) =>
            `<button class="seg-btn ${(c.server.close_action || "") === v ? "active" : ""}" data-act="close-seg" data-v="${v}">${label}</button>`).join("")}
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("autostart")}</div><div class="desc">${t("autostart_desc")}</div></div>
        <label class="switch"><input type="checkbox" data-change="autostart" ${S.autostart ? "checked" : ""}><span class="knob"></span></label>
      </div>
    </div>

    <div class="card fade-in">
      <div class="card-header"><div><div class="card-title">${t("appearance")}</div></div></div>
      <div class="row">
        <div class="row-main"><div class="label">${t("theme")}</div></div>
        <div class="segmented" style="max-width:240px">
          <button class="seg-btn ${S.theme === "auto" ? "active" : ""}" data-act="theme-set" data-theme="auto">${t("theme_auto")}</button>
          <button class="seg-btn ${S.theme === "light" ? "active" : ""}" data-act="theme-set" data-theme="light">${t("theme_light")}</button>
          <button class="seg-btn ${S.theme === "dark" ? "active" : ""}" data-act="theme-set" data-theme="dark">${t("theme_dark")}</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("language")}</div></div>
        <div class="segmented" style="max-width:240px">
          <button class="seg-btn ${LANG === "zh" ? "active" : ""}" data-act="lang-set" data-lang="zh">${t("lang_zh")}</button>
          <button class="seg-btn ${LANG === "en" ? "active" : ""}" data-act="lang-set" data-lang="en">${t("lang_en")}</button>
        </div>
      </div>
      <div class="row">
        <div class="row-main"><div class="label">${t("config_backup")}</div><div class="desc">${t("config_backup_desc")}</div></div>
        <div class="btn-row">
          <button class="btn btn-sm btn-plain" data-act="cfg-export">${t("common_export")}</button>
          <button class="btn btn-sm btn-plain" data-act="cfg-import">${t("common_import")}</button>
          <input type="file" id="import-file" accept=".json" style="display:none">
        </div>
      </div>
    </div>`;
  },

  logs() {
    return `
    <div class="view-title fade-in">${t("view_title_logs")}
      <div class="btn-row">
        <div class="segmented" style="max-width:240px">
          ${["all", "ok", "fail"].map(f => `<button class="seg-btn ${S.logFilter === f ? "active" : ""}" data-act="log-filter" data-f="${f}">${{ all: t("log_filter_all"), ok: t("log_filter_ok"), fail: t("log_filter_fail") }[f]}</button>`).join("")}
        </div>
        <button class="btn btn-sm btn-plain" data-act="logs-clear">${t("common_clear")}</button>
        <button class="btn btn-sm btn-plain" data-act="logs-export">${t("common_export")}</button>
      </div>
    </div>
    <div class="card fade-in"><div id="logList">${logListHtml()}</div></div>`;
  },
};
