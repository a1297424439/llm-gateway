"use strict";
/* ============ 动作处理 ============ */
const ACTIONS = {
  nav(d) { S.view = d.view; render(); },
  refresh() { refresh(); },
  copy(d) { copyText(d.copy); },
  "theme-cycle"() {
    S.theme = S.theme === "auto" ? "light" : S.theme === "light" ? "dark" : "auto";
    applyTheme();
    toast(t("theme_toast", { label: t({ auto: "theme_follow_system", light: "theme_light_label", dark: "theme_dark_label" }[S.theme]) }));
    if (S.view === "settings") render();
  },
  "theme-set"(d) { S.theme = d.theme; applyTheme(); render(); },
  "lang-set"(d) { setLang(d.lang); toast(t("lang_switched")); render(); },
  "key-toggle"() { S.keyVisible = !S.keyVisible; render(); },
  async "key-regen"() {
    if (!(await confirmDlg(t("key_regen_confirm_title"), t("key_regen_confirm_msg"), t("key_regen_btn")))) return;
    try { await api("/api/server/regenerate-key", { method: "POST" }); toast(t("key_regen_done")); S.keyVisible = true; await refresh(); }
    catch (e) { toast(e.message, "err"); }
  },
  async "port-regen"() {
    if (!(await confirmDlg(t("port_regen_confirm_title"), t("port_regen_confirm_msg"), t("port_change_btn")))) return;
    try { const r = await api("/api/server/regenerate-port", { method: "POST" }); toast(t("port_regen_done", { port: r.port })); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  },
  async "server-restart"() {
    if (!(await confirmDlg(t("restart_confirm_title"), t("restart_confirm_msg"), t("restart_btn"), false))) return;
    try { await api("/api/server/restart", { method: "POST" }); toast(t("restarting")); }
    catch (e) { toast(e.message, "err"); }
  },
  async "mode-seg"(d) { await saveSettings({ mode: d.mode }); toast(t(d.mode === "safe" ? "mode_switched_safe" : "mode_switched_smart")); },
  async "host-seg"(d) { await saveSettings({ server: { host: d.host } }); },
  "provider-add"() { providerModal(null); },
  "provider-edit"(d) { const p = (cfg().providers || []).find(x => x.id === d.id); if (p) providerModal(p); },
  async "provider-del"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.id);
    if (!p) return;
    if (!(await confirmDlg(t("provider_del_confirm_title", { name: p.name }), t("provider_del_confirm_msg"), t("common_delete")))) return;
    try { await api("/api/providers/" + p.id, { method: "DELETE" }); toast(t("provider_deleted")); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  },
  async "provider-refresh"(d) {
    toast(t("provider_refreshing"));
    try {
      const r = await api(`/api/providers/${d.id}/refresh`, { method: "POST" });
      if (r.ok) toast(t("provider_refresh_ok", { count: r.models.length }));
      else toast(t("provider_refresh_fail") + r.error, "err");
      await refresh();
    } catch (e) { toast(e.message, "err"); }
  },
  "model-add"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.id);
    if (p) modelAddModal(p);
  },
  "provider-models"(d) {
    if (S.expandedProviders.has(d.id)) S.expandedProviders.delete(d.id);
    else S.expandedProviders.add(d.id);
    render();
  },
  async "chip-toggle"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.pid);
    if (!p) return;
    const s = p.sched_models = p.sched_models || [];
    const i = s.indexOf(d.model);
    if (i >= 0) s.splice(i, 1); else s.push(d.model);
    render();
    await _putSched(d.pid);
  },
  async "chip-all"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.id);
    if (!p) return;
    const s = p.sched_models = p.sched_models || [];
    for (const m of (p.fetched_models || [])) if (!s.includes(m)) s.push(m);
    render();
    await _putSched(d.id);
  },
  async "chip-none"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.id);
    if (!p) return;
    p.sched_models = [];
    render();
    try { await api("/api/providers/" + d.id, { method: "PUT", body: JSON.stringify({ sched_models: [] }) }); }
    catch (e) { toast(e.message, "err"); refresh(); }
  },
  async "close-seg"(d) { await saveSettings({ server: { close_action: d.v } }); },
  "tier-collapse"(d) {
    const ti = parseInt(d.ti, 10);
    const arr = S.collapsedTiers;
    const i = arr.indexOf(ti);
    if (i >= 0) arr.splice(i, 1); else arr.push(ti);
    localStorage.setItem("gw_collapsed", JSON.stringify(arr));
    render();
  },
  "cd-clear"() { api("/api/cooldowns/clear", { method: "POST", body: "{}" }).then(() => { toast(t("cd_cleared")); refresh(); }); },
  "cd-clear-one"(d) { api("/api/cooldowns/clear", { method: "POST", body: JSON.stringify({ key: d.key }) }).then(() => refresh()); },
  "log-filter"(d) { S.logFilter = d.f; render(); },
  "logs-clear"() { api("/api/logs/clear", { method: "POST" }).then(() => refresh()); },
  "logs-export"() {
    fetch("/api/logs/export", { headers: S.key ? { Authorization: "Bearer " + S.key } : {} })
      .then(r => r.blob()).then(b => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(b);
        a.download = "llm-gateway-logs-" + new Date().toISOString().slice(0, 10) + ".json";
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        toast(t("logs_exported"));
      });
  },
  "log-toggle"(d) {
    const k = String(d.k);
    if (S.expandedLogs.has(k)) S.expandedLogs.delete(k); else S.expandedLogs.add(k);
    render();
  },
  "cfg-export"() {
    fetch("/api/config/export", { headers: S.key ? { Authorization: "Bearer " + S.key } : {} })
      .then(r => r.blob()).then(b => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(b); a.download = "llm-gateway-config.json"; a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        toast(t("config_exported"));
      });
  },
  "cfg-import"() { $("#import-file").click(); },
  "open-promo"() {
    api("/api/open-url", { method: "POST", body: JSON.stringify({ url: "https://aifangan.top" }) })
      .catch(() => toast(t("toast_opened"), "err"));
  },
  "sponsor-open"() {
    toast(t("sponsor_placeholder"));
  },
  "sponsor-copy"(d) { copyText(d.copy || "https://example.com/sponsor", t("sponsor_copied")); },
  "chip-ctx"(d, el) {
    // 阻止冒泡到 chip-toggle
    if (event) { event.stopPropagation(); event.preventDefault(); }
    const p = (cfg().providers || []).find(x => x.id === d.pid);
    if (!p) return;
    const m = d.model;
    const cur = (p.model_ctx || {})[m] || [0, false];
    const curVal = cur[0] || 0;
    const opts = [0, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576];
    openModal(`
      <div class="modal-title">${t("ctx_edit_title", { model: esc(m) })}</div>
      <div class="modal-msg">${t("ctx_current")}${curVal ? fmtCtx(curVal) + t(cur[1] ? "ctx_exact_label" : "ctx_guess_label") : t("ctx_unknown_short")}</div>
      <div class="form-grid">
        <div class="form-item">
          <label>${t("ctx_length_label")}</label>
          <select id="ctx-sel">
            ${opts.map(v => `<option value="${v}" ${v === curVal ? "selected" : ""}>${v === 0 ? t("ctx_unknown_short") : fmtCtx(v)}${v === 0 ? "" : " tokens"}</option>`).join("")}
          </select>
        </div>
        <div class="form-item">
          <label>${t("ctx_manual_input")}</label>
          <input type="number" id="ctx-input" min="0" max="2000000" placeholder="${t("ctx_placeholder")}" value="${curVal || ""}">
        </div>
      </div>
      <div class="modal-btns"><button class="btn btn-plain" id="ctx-cancel">${t("common_cancel")}</button><button class="btn btn-primary" id="ctx-save">${t("common_save")}</button></div>`);
    $("#ctx-sel").onchange = e => { $("#ctx-input").value = e.target.value; };
    $("#ctx-cancel").onclick = closeModal;
    $("#ctx-save").onclick = async () => {
      const v = parseInt($("#ctx-input").value || "0", 10);
      if (v < 0 || v > 2000000) { toast(t("ctx_range_err"), "err"); return; }
      if (!p.model_ctx) p.model_ctx = {};
      p.model_ctx[m] = [v, true]; // 手动标注 = exact
      closeModal();
      render();
      try {
        await api("/api/providers/" + p.id, { method: "PUT", body: JSON.stringify({ model_context: p.model_ctx }) });
        toast(t("ctx_updated"));
      } catch (e) { toast(e.message, "err"); refresh(); }
    };
  },
  "modal-backdrop"() { closeModal(); },
  "provider-ctx"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.id);
    if (!p) return;
    const models = (p.fetched_models && p.fetched_models.length ? p.fetched_models : p.sched_models) || [];
    if (!models.length) { toast(t("no_models_fetch_first"), "err"); return; }
    const rows = models.map(m => {
      const cur = (p.model_ctx || {})[m] || (p.model_context || {})[m] || [0, false];
      const v = cur[0] || 0;
      return `
      <div class="form-item">
        <label>${esc(m)}</label>
        <input type="number" min="0" max="2000000" data-ctx-input="${esc(m)}" placeholder="${t("ctx_zero_unknown")}" value="${v || ""}">
      </div>`;
    }).join("");
    openModal(`
      <div class="modal-title">${t("ctx_batch_title", { name: esc(p.name) })}</div>
      <div class="modal-msg">${t("ctx_batch_hint")}</div>
      <div class="form-grid" style="max-height:46vh;overflow:auto">${rows}</div>
      <div class="modal-btns"><button class="btn btn-plain" id="pcx-cancel">${t("common_cancel")}</button><button class="btn btn-primary" id="pcx-save">${t("common_save")}</button></div>`);
    $("#pcx-cancel").onclick = closeModal;
    $("#pcx-save").onclick = async () => {
      const mc = {};
      $$("#modal [data-ctx-input]").forEach(inp => {
        const v = Math.max(0, Math.min(2000000, parseInt(inp.value || "0", 10) || 0));
        mc[inp.dataset.ctxInput] = [v, true];
      });
      closeModal();
      try {
        await api("/api/providers/" + p.id, { method: "PUT", body: JSON.stringify({ model_context: mc }) });
        toast(t("ctx_saved"));
        await refresh();
      } catch (e) { toast(e.message, "err"); refresh(); }
    };
  },
};

const CHANGES = {
  async "autostart"(d, el) {
    try {
      const r = await api("/api/autostart", { method: "POST", body: JSON.stringify({ enabled: el.checked }) });
      if (r.ok !== false) toast(t(el.checked ? "autostart_enabled" : "autostart_disabled"));
      else { toast(r.error || t("settings_failed"), "err"); el.checked = !el.checked; }
    } catch (e) { toast(e.message, "err"); el.checked = !el.checked; }
  },
  "provider-enabled"(d, el) {
    api("/api/providers/" + d.id, { method: "PUT", body: JSON.stringify({ enabled: el.checked }) })
      .then(async () => { toast(t(el.checked ? "provider_enabled" : "provider_disabled")); await refresh(); })
      .catch(e => { toast(e.message, "err"); refresh(); });
  },
  "dd-toggle"(d, el) {
    const list = $("#recList");
    if (list) list.style.display = list.style.display === "none" ? "block" : "none";
  },
  async "dd-pick"(d, el) {
    const list = $("#recList");
    if (list) list.style.display = "none";
    await saveSettings({ recommended_model: d.v });
    toast(t("rec_model_set", { name: d.v }));
  },
  "provider-priority"(d, el) {
    const v = Math.max(1, parseInt(el.value || "1", 10));
    api("/api/providers/" + d.id, { method: "PUT", body: JSON.stringify({ priority: v }) })
      .then(() => refresh()).catch(e => toast(e.message, "err"));
  },
  async "settings-num"(d, el) {
    const v = Math.max(parseInt(el.min || "1", 10), Math.min(parseInt(el.max || "999999", 10), parseInt(el.value || "0", 10) || 1));
    el.value = v;
    await saveSettings({ [d.sect]: { [d.field]: v } });
  },
  async "settings-port"(d, el) {
    const v = parseInt(el.value || "0", 10);
    if (!v || v < 1 || v > 65535) { toast(t("port_range_err"), "err"); render(); return; }
    if (v === cfg().server.port) return;
    if (!(await confirmDlg(t("port_change_confirm_title"), t("port_change_confirm_msg", { port: v }), t("port_change_btn")))) { render(); return; }
    try { await api("/api/server/set-port", { method: "POST", body: JSON.stringify({ port: v }) }); toast(t("port_saved", { port: v })); await refresh(); }
    catch (e) { toast(e.message, "err"); render(); }
  },
};

/* ============ 事件绑定 ============ */
window.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

document.addEventListener("click", e => {
  if (S.suppressClick) return;
  if (!e.target.closest(".dd")) {
    $$(".dd-list").forEach(l => l.style.display = "none");
  }
  const el = e.target.closest("[data-act]");
  if (!el) return;
  const fn = ACTIONS[el.dataset.act];
  if (fn) { e.preventDefault(); fn(el.dataset, el); }
});
document.addEventListener("change", e => {
  const el = e.target.closest("[data-change]");
  if (!el) return;
  const fn = CHANGES[el.dataset.change];
  if (fn) fn(el.dataset, el);
});
document.addEventListener("change", e => {
  if (e.target && e.target.id === "import-file" && e.target.files && e.target.files[0]) {
    const f = e.target.files[0];
    f.text().then(async txt => {
      if (!(await confirmDlg(t("import_confirm_title"), t("import_confirm_msg"), t("common_import"), false))) return;
      S.busy = true;
      try { await api("/api/config/import", { method: "POST", body: txt }); toast(t("config_imported")); await refresh(); }
      catch (e) { toast(e.message, "err"); } finally { S.busy = false; }
    });
    e.target.value = "";
  }
});

/* ============ 初始化 ============ */
applyTheme();
refresh();
api("/api/presets").then(r => { S.presets = r.presets || []; }).catch(() => { });
api("/api/autostart").then(r => { S.autostart = !!r.enabled; if (S.view === "settings") render(); }).catch(() => { });
setInterval(() => {
  if (!document.hidden && !S.busy && !$("#modal-root").firstElementChild &&
    (S.view === "dashboard" || S.view === "logs")) refresh({ dynamic: true });
}, 3000);

// 拦截意外刷新与非输入区右键菜单
document.addEventListener("keydown", e => {
  if (e.key === "F5" || ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === "r" || e.key === "R"))) e.preventDefault();
});
document.addEventListener("contextmenu", e => {
  const t = e.target;
  if (!(t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable))) e.preventDefault();
});


