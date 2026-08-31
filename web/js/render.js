"use strict";
/* ============ 渲染骨架 ============ */
let cdHash = "", logHash = "", dashKey = "";
function render() {
  if (typeof D !== "undefined" && D) _cancelDrag();
  renderTop();
  renderTabbar();
  const v = $("#view");
  if (S.err && !S.data) {
    v.innerHTML = `<div class="view-title fade-in">${t('tab_dashboard')}</div><div class="card card-pad fade-in"><div class="empty"><div class="big">${t('conn_fail')}</div><div class="hint">${esc(S.err)}</div></div></div>`;
    return;
  }
  const banner = S.data && S.data.pending_restart
    ? `<div class="banner"><div class="banner-inner"><span>${t('conn_restart_banner')}</span><button class="btn btn-sm btn-primary" data-act="server-restart">${t('conn_restart_now')}</button></div></div>`
    : "";
  $("#restart-banner").innerHTML = banner;
  const sy = window.scrollY;
  const fn = VIEWS[S.view] || VIEWS.dashboard;
  v.innerHTML = fn();
  window.scrollTo(0, sy);
  cdHash = hashStr(JSON.stringify((S.data && S.data.cooldowns) || []));
  logHash = logHashOf();
  dashKey = [cfg().server.port, cfg().server.key, cfg().mode, !!(S.data && S.data.pending_restart)].join("|");
}
function logHashOf() {
  const logs = ((S.data && S.data.logs) || []).slice(0, 300)
    .map(l => [l.ts, l.ok, l.ms, l.alias, l.model, l.provider, l.error, l.attempts]);
  return hashStr(JSON.stringify(logs) + "|" + S.logFilter);
}
function updateDynamic() {
  const d = S.data;
  if (!d) return;
  const c = cfg();
  const k = [c.server.port, c.server.key, c.mode, !!d.pending_restart].join("|");
  if (k !== dashKey) { render(); return; }
  renderTop();
  if (S.view === "dashboard") {
    setText("#uptimeText", fmtDur(d.uptime || 0));
    const st = d.stats || {}, cds = d.cooldowns || [];
    setText("#st-total", st.total ?? 0);
    setText("#st-rate", (st.success_rate ?? 100) + "%");
    const ce = $("#st-cool");
    if (ce) { ce.textContent = String(cds.length); ce.style.color = cds.length ? "var(--orange)" : "inherit"; }
    setText("#st-prov", (c.providers || []).filter(p => p.enabled).length);
    const h = hashStr(JSON.stringify(cds));
    if (h !== cdHash) {
      cdHash = h;
      const el = $("#cdList"); if (el) el.innerHTML = cdListHtml(cds);
      const cb = $("#cdClearBtn");
      if (cb) cb.innerHTML = cds.length ? `<button class="btn btn-sm btn-plain" data-act="cd-clear">${t('cd_clear_all')}</button>` : "";
    }
  } else if (S.view === "logs") {
    const h = logHashOf();
    if (h !== logHash) { logHash = h; const el = $("#logList"); if (el) el.innerHTML = logListHtml(); }
  }
}
function renderTop() {
  $("#verText").textContent = "LLM Gateway" + (S.data ? " · v" + S.data.version : "");
  const b = $("#modeBadge");
  const mode = cfg().mode;
  b.textContent = mode === "safe" ? t('mode_safe') : t('mode_smart');
  b.className = "badge " + (mode === "safe" ? "badge-green" : "badge-blue");
}
function renderTabbar() {
  $("#tabbar").innerHTML = TABS.map(tb =>
    `<button class="tab ${S.view === tb.id ? "active" : ""}" data-act="nav" data-view="${tb.id}">${tb.icon}<span>${t("tab_" + tb.id)}</span></button>`).join("");
}

/* ============ 辅助 HTML 生成 ============ */
function logListHtml() {
  let logs = (S.data && S.data.logs) || [];
  if (S.logFilter !== "all") logs = logs.filter(l => S.logFilter === "ok" ? l.ok : !l.ok);
  if (!logs.length) return `<div class="empty">${t('log_empty')}</div>`;
  return logs.map(l => {
    const dot = l.ok ? "ok" : "fail";
    const route = l.provider ? `${esc(l.provider)} / ${esc(l.model || "")}` : t('log_no_provider');
    const k = String(l.ts);
    return `
        <div class="log-row" data-act="log-toggle" data-k="${k}">
          <div class="log-line">
            <span class="log-dot ${dot}"></span>
            <div class="log-text">
              <div>${esc(l.alias || l.model || "—")}${l.stream ? ' <span class="badge badge-gray" style="font-size:10px">stream</span>' : ""}</div>
              <div class="route">${route}</div>
            </div>
            <span class="log-ms">${l.ms ?? "—"}ms</span>
            <span class="mono" style="font-size:11px;color:var(--text3)">${fmtTime(l.ts)}</span>
          </div>
          ${S.expandedLogs.has(k) ? `<div class="log-detail">${logDetail(l)}</div>` : ""}
        </div>`;
  }).join("");
}

function cdListHtml(cds) {
  if (!cds.length) return `<div class="empty">${t('cd_empty')}</div>`;
  return cds.map(cd => `
        <div class="cd-row">
          <span class="cd-dot"></span>
          <div class="row-main">
            <div class="label mono" style="font-size:13px">${esc(cd.provider)} · ${esc(cd.model)}</div>
            <div class="desc">${t('cd_failed', {count: cd.fails, dur: fmtDur(cd.remaining)})}</div>
            ${cd.last_error ? `<div class="desc mono" style="font-size:11px;word-break:break-all">${esc(cd.last_error)}</div>` : ""}
          </div>
          <button class="btn btn-sm btn-plain" data-act="cd-clear-one" data-key="${esc(cd.key)}">${t('cd_clear_one')}</button>
        </div>`).join("");
}

function logDetail(l) {
  const parts = [];
  if (l.error) parts.push(`<div class="hint" style="color:var(--red)">${t('log_err_prefix')}${esc(l.error)}</div>`);
  if (Array.isArray(l.attempts) && l.attempts.length) {
    parts.push('<div class="code">' + esc(l.attempts.map(a =>
      `→ ${a.provider || "?"} / ${a.model || "?"}${a.skipped ? "  [" + t('attempt_skip') + ":" + a.skipped + "]" : ""}${a.error ? "  [" + t('attempt_fail') + " HTTP " + (a.status || "?") + ": " + a.error + "]" : ""}${a.cooldown ? "  [" + t('attempt_cooling') + "]" : ""}`
    ).join("\n")) + '</div>');
  }
  return parts.join("") || `<div class="hint">${t('log_no_detail')}</div>`;
}

function buildCurl(url, key, model) {
  return `curl ${url}/chat/completions \\\n  -H "Authorization: Bearer ***" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "model": "${model || t('curl_model')}",\n    "messages": [{"role": "user", "content": "${t('curl_hello')}"}]\n  }'`;
}

function modeDesc(m) {
  return m === "safe"
    ? t('mode_safe_desc')
    : t('mode_smart_desc');
}

function tierOf(p) {
  const pr = p.priority || 1;
  return pr < 10 ? 0 : pr < 20 ? 1 : 2;
}
function chipHtml(p, m) {
  const on = (p.sched_models || []).includes(m);
  const cls = on ? "selected" : "off";
  const tip = on ? t('chip_drag_reorder')
            : t('chip_drag_add');
  return `<span class="chip ${cls}" data-mdrag="${esc(m)}" data-pid="${esc(p.id)}" data-act="chip-toggle" data-model="${esc(m)}" title="${tip}">${on ? "✓ " : "+ "}${esc(m)}${ctxBadge(p, m)}</span>`;
}
function providerCard(p, tierIdx) {
  const expanded = S.expandedProviders.has(p.id);
  const test = p.last_test;
  const sel = p.sched_models || [];
  const all = p.fetched_models || [];
  // 已选模型排前面（保持用户排序），未选模型排后面
  const selOrdered = sel.filter(m => all.includes(m)).concat(sel.filter(m => !all.includes(m)));
  const rest = all.filter(m => !sel.includes(m));
  const restCap = expanded ? 500 : Math.max(0, 24 - selOrdered.length);
  const restShown = rest.slice(0, restCap);
  const hiddenCount = rest.length - restShown.length;
  return `
  <div class="card provider-card tier-${tierIdx}" style="${p.enabled ? "" : "opacity:.6"}">
    <div class="pc-top" data-drag="${esc(p.id)}" title="${t('drag_card_title')}">
      <span class="drag-dot">⠿</span>
      <div class="row-main">
        <div class="provider-title">${esc(p.name)}
          <span class="badge ${(p.trusted ?? p.domestic) ? "badge-green" : "badge-gray"}">${(p.trusted ?? p.domestic) ? t('p_trusted') : t('p_normal')}</span>
          <span class="badge badge-blue">${p.adapter === "anthropic" ? t('p_anthropic') : t('p_openai')}</span>
          ${p.enabled ? "" : `<span class="badge badge-orange">${t('p_disabled')}</span>`}
        </div>
        <div class="provider-url">${esc(p.base_url)}</div>
      </div>
      <span class="badge badge-blue" style="flex:none">${t('p_selected', {a: sel.length, b: all.length})}</span>
      <label class="switch"><input type="checkbox" data-change="provider-enabled" data-id="${esc(p.id)}" ${p.enabled ? "checked" : ""}><span class="knob"></span></label>
    </div>
    ${test ? `<div class="provider-meta"><span class="badge ${test.ok ? "badge-green" : "badge-red"}">${test.ok ? "✓" : "✕"} ${esc(test.detail || "")}</span></div>` : ""}
    <div class="chips">
      <button class="chip chip-add" data-act="provider-refresh" data-id="${esc(p.id)}">⟳ ${t('p_refresh')}</button>
      <button class="chip chip-add" data-act="model-add" data-id="${esc(p.id)}">＋ ${t('p_manual_add')}</button>
      ${all.length ? `<button class="chip chip-add" data-act="chip-all" data-id="${esc(p.id)}">${t('p_select_all')}</button>
      <button class="chip chip-add" data-act="chip-none" data-id="${esc(p.id)}">${t('p_select_none')}</button>` : ""}
      ${selOrdered.length ? `<span class="chip sep sel-sep">${t('p_selected_group')}</span>` + selOrdered.map(m => chipHtml(p, m)).join("") : ""}
      ${restShown.length ? `<span class="chip sep">${t('p_unselected_group')}</span>` + restShown.map(m => chipHtml(p, m)).join("") : ""}
      ${hiddenCount > 0 ? `<span class="chip chip-add" data-act="provider-models" data-id="${esc(p.id)}">${expanded ? t('common_collapse') : t('p_more', {count: hiddenCount})}</span>` : ""}
    </div>
    <div class="row pc-foot">
      <div class="btn-row">
        <button class="btn btn-sm btn-plain" data-act="provider-edit" data-id="${esc(p.id)}">${t('common_edit')}</button>
        <button class="btn btn-sm btn-plain" data-act="provider-ctx" data-id="${esc(p.id)}">${t('p_model_ctx')}</button>
        <button class="btn btn-sm btn-danger" data-act="provider-del" data-id="${esc(p.id)}">${t('common_delete')}</button>
      </div>
      ${p.note ? `<span class="hint">${esc(p.note)}</span>` : ""}
    </div>
  </div>`;
}

/* ============ 模态框 ============ */
function openModal(html) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop" data-act="modal-backdrop"><div class="modal-sheet" onclick="event.stopPropagation()">${html}</div></div>`;
  requestAnimationFrame(() => root.firstElementChild && root.firstElementChild.classList.add("show"));
}
function closeModal() {
  const root = $("#modal-root");
  const b = root.firstElementChild;
  if (b) { b.classList.remove("show"); setTimeout(() => { root.innerHTML = ""; }, 180); }
}
function confirmDlg(title, msg, okText = null, danger = true) {
  okText = okText || t('common_confirm');
  return new Promise(res => {
    openModal(`<div class="modal-title">${esc(title)}</div><div class="modal-msg">${esc(msg)}</div>
      <div class="modal-btns"><button class="btn btn-plain" id="cfm-no">${t('common_cancel')}</button>
      <button class="btn ${danger ? "btn-danger" : "btn-primary"}" id="cfm-yes">${esc(okText)}</button></div>`);
    $("#cfm-no").onclick = () => { closeModal(); res(false); };
    $("#cfm-yes").onclick = () => { closeModal(); res(true); };
  });
}
function showKeyModal() {
  openModal(`<div class="modal-title">${t('key_modal_title')}</div>
    <div class="modal-msg">${t('key_modal_msg')}</div>
    <div class="form-grid"><div class="form-item"><input type="password" id="gwkey-input" placeholder="sk-lg-..." autocomplete="off"></div></div>
    <div class="modal-btns"><button class="btn btn-plain" id="gwkey-cancel">${t('common_cancel')}</button><button class="btn btn-primary" id="gwkey-ok">${t('key_connect')}</button></div>`);
  $("#gwkey-cancel").onclick = closeModal;
  $("#gwkey-ok").onclick = () => {
    const v = $("#gwkey-input").value.trim();
    if (!v) return;
    S.key = v; localStorage.setItem("gw_key", v);
    closeModal(); refresh();
  };
}
function providerModal(existing) {
  const presets = S.presets || [];
  const dom = presets.filter(p => p.trusted), intl = presets.filter(p => !p.trusted);
  openModal(`
    <div class="modal-title">${existing ? t('p_edit_title') : t('p_add_title')}</div>
    <div class="form-grid">
      <div class="form-item">
        <label>${t('p_preset_label')}</label>
        <select id="pf-preset">
          <option value="">${t('p_preset_custom')}</option>
          <optgroup label="${t('p_preset_trusted')}">${dom.map((p, i) => `<option value="d${i}">${esc(p.name)}</option>`).join("")}</optgroup>
          <optgroup label="${t('p_preset_other')}">${intl.map((p, i) => `<option value="i${i}">${esc(p.name)}</option>`).join("")}</optgroup>
        </select>
      </div>
      <div class="form-item"><label>${t('p_name')}</label><input id="pf-name" placeholder="${t('p_name_ph')}" value="${esc(existing ? existing.name : "")}"></div>
      <div class="form-item"><label>${t('p_url')}</label><input id="pf-url" placeholder="https://api.example.com/v1" value="${esc(existing ? existing.base_url : "")}"></div>
      <div class="form-item"><label>${t('p_api_key')}</label><input id="pf-key" type="password" placeholder="sk-..." autocomplete="off" value="${esc(existing ? existing.api_key : "")}"></div>
      <div class="form-item"><label>${t('p_adapter')}</label>
        <select id="pf-adapter">
          <option value="openai" ${!existing || existing.adapter !== "anthropic" ? "selected" : ""}>${t('p_adapter_openai')}</option>
          <option value="anthropic" ${existing && existing.adapter === "anthropic" ? "selected" : ""}>${t('p_adapter_anthropic')}</option>
        </select>
      </div>
      <div class="form-item"><div class="rowlike"><span><b style="font-size:13.5px">${t('p_trusted_label')}</b><div class="hint">${t('p_trusted_hint')}</div></span>
        <label class="switch"><input type="checkbox" id="pf-trusted" ${existing && (existing.trusted ?? existing.domestic) ? "checked" : ""}><span class="knob"></span></label></div></div>
      <div class="form-item"><label>${t('p_note')}</label><input id="pf-note" value="${esc(existing ? existing.note || "" : "")}"></div>
    </div>
    <div class="modal-btns"><button class="btn btn-plain" id="pf-cancel">${t('common_cancel')}</button><button class="btn btn-primary" id="pf-save">${existing ? t('p_save') : t('p_add')}</button></div>`);
  $("#pf-preset").onchange = e => {
    const v = e.target.value;
    if (!v) return;
    const p = v[0] === "d" ? dom[+v.slice(1)] : intl[+v.slice(1)];
    if (!p) return;
    $("#pf-name").value = p.name; $("#pf-url").value = p.base_url;
    $("#pf-adapter").value = p.adapter; $("#pf-trusted").checked = !!(p.trusted ?? p.domestic);
  };
  $("#pf-cancel").onclick = closeModal;
  $("#pf-save").onclick = async () => {
    const body = {
      name: $("#pf-name").value.trim(), base_url: $("#pf-url").value.trim(),
      api_key: $("#pf-key").value.trim(), adapter: $("#pf-adapter").value,
      trusted: $("#pf-trusted").checked, note: $("#pf-note").value.trim(),
    };
    if (!body.name || !body.base_url.startsWith("http")) { toast(t('p_require_name'), "err"); return; }
    S.busy = true;
    try {
      if (existing) await api("/api/providers/" + existing.id, { method: "PUT", body: JSON.stringify(body) });
      else await api("/api/providers", { method: "POST", body: JSON.stringify(body) });
      closeModal(); toast(existing ? t('p_saved') : t('p_added'));
      await refresh();
    } catch (e) { toast(e.message, "err"); } finally { S.busy = false; }
  };
}
function modelAddModal(p) {
  openModal(`<div class="modal-title">${t('m_add_title', {name: esc(p.name)})}</div>
    <div class="form-grid"><div class="form-item">
      <label>${t('m_name_label')}</label>
      <input id="ma-name" placeholder="${t('m_name_ph')}">
      <div class="hint" style="margin-top:6px">${t('m_add_hint')}</div>
    </div></div>
    <div class="modal-btns"><button class="btn btn-plain" id="ma-cancel">${t('common_cancel')}</button><button class="btn btn-primary" id="ma-ok">${t('p_add')}</button></div>`);
  $("#ma-cancel").onclick = closeModal;
  $("#ma-ok").onclick = async () => {
    const raw = $("#ma-name").value.trim();
    if (!raw) { toast(t('m_require_name'), "err"); return; }
    const names = raw.split(/[,，\s]+/).filter(Boolean);
    S.busy = true;
    try {
      for (const n of names) {
        await api(`/api/providers/${p.id}/models-add`, { method: "POST", body: JSON.stringify({ model: n }) });
      }
      closeModal(); toast(t('m_added', {count: names.length}));
      await refresh();
    } catch (e) { toast(e.message, "err"); } finally { S.busy = false; }
  };
}

async function saveSettings(patch) {
  S.busy = true;
  try { await api("/api/settings", { method: "POST", body: JSON.stringify(patch) }); await refresh(); }
  catch (e) { toast(e.message, "err"); } finally { S.busy = false; }
}

/* 点 ✕ 的确认框（主进程通过 evaluate_js 调用） */
window.__askClose = function () {
  if (document.querySelector("#closeAsk")) return;
  openModal(`<div class="modal-title">${t('close_title')}</div>
    <div class="modal-msg">${t('close_msg')}</div>
    <label class="hint" style="display:flex;align-items:center;gap:8px;margin:12px 18px 0;cursor:pointer">
      <input type="checkbox" id="ca-remember" style="width:auto"> ${t('close_remember')}
    </label>
    <div class="modal-btns" style="flex-direction:column">
      <button class="btn btn-primary" id="ca-hide" style="height:44px">${t('close_hide')}</button>
      <button class="btn btn-danger" id="ca-quit" style="height:44px">${t('close_quit')}</button>
    </div>`);
  $("#ca-hide").onclick = async () => {
    if ($("#ca-remember") && $("#ca-remember").checked) await saveSettings({ server: { close_action: "hide" } });
    try { await api("/api/window/hide", { method: "POST", body: "{}" }); } catch (e) { }
    closeModal();
  };
  $("#ca-quit").onclick = async () => {
    if ($("#ca-remember") && $("#ca-remember").checked) {
      try { await api("/api/settings", { method: "POST", body: JSON.stringify({ server: { close_action: "quit" } }) }); } catch (e) { }
    }
    toast(t('close_quitting'));
    try { await api("/api/window/quit", { method: "POST", body: "{}" }); } catch (e) { }
  };
};


