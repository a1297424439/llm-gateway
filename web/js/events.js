"use strict";
/* ============ 动作处理 ============ */
const ACTIONS = {
  nav(d) { S.view = d.view; render(); },
  refresh() { refresh(); },
  copy(d) { copyText(d.copy); },
  "theme-cycle"() {
    S.theme = S.theme === "auto" ? "light" : S.theme === "light" ? "dark" : "auto";
    applyTheme(); toast("主题：" + { auto: "跟随系统", light: "浅色", dark: "深色" }[S.theme]);
    if (S.view === "settings") render();
  },
  "theme-set"(d) { S.theme = d.theme; applyTheme(); render(); },
  "key-toggle"() { S.keyVisible = !S.keyVisible; render(); },
  async "key-regen"() {
    if (!(await confirmDlg("重新生成 API Key？", "旧的 Key 将立即失效，所有已接入的客户端都需要更换新 Key。", "重新生成"))) return;
    try { await api("/api/server/regenerate-key", { method: "POST" }); toast("新 Key 已生成"); S.keyVisible = true; await refresh(); }
    catch (e) { toast(e.message, "err"); }
  },
  async "port-regen"() {
    if (!(await confirmDlg("随机更换监听端口？", "将生成一个新的随机端口，保存后需要重启程序生效。", "更换"))) return;
    try { const r = await api("/api/server/regenerate-port", { method: "POST" }); toast("新端口 " + r.port + "，重启后生效"); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  },
  async "check-update"() {
    const hint = document.getElementById("updateHint");
    const btn = document.getElementById("applyUpdateBtn");
    if (hint) hint.textContent = "（检查中…）";
    try {
      const r = await api("/api/check-update");
      if (r.has_update) {
        if (hint) hint.textContent = "（发现新版本 v" + r.latest + "）";
        if (btn) btn.style.display = "";
        toast("发现新版本 v" + r.latest + "，可点击「立即更新」自动升级");
      } else {
        if (hint) hint.textContent = "（已是最新 v" + r.current + "）";
        if (btn) btn.style.display = "none";
        toast("已是最新版本 v" + r.current);
      }
    } catch (e) {
      if (hint) hint.textContent = "（检查失败）";
      toast("检查更新失败：" + e.message, "err");
    }
  },
  async "apply-update"() {
    if (!(await confirmDlg("立即更新？", "将下载最新版安装包并静默安装，安装过程中程序会自动重启。", "更新", true))) return;
    const btn = document.getElementById("applyUpdateBtn");
    const hint = document.getElementById("updateHint");
    if (btn) { btn.disabled = true; btn.textContent = "更新中…"; }
    if (hint) hint.textContent = "（正在下载最新版，请稍候…）";
    try {
      const r = await api("/api/apply-update", { method: "POST" });
      toast(r.message || "更新已开始");
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "立即更新"; }
      if (hint) hint.textContent = "（更新失败）";
      toast("更新失败：" + e.message, "err");
    }
  },
  async "server-restart"() {
    if (!(await confirmDlg("重启网关服务？", "服务将退出并以新配置重新启动，面板会短暂不可用。", "重启", false))) return;
    try { await api("/api/server/restart", { method: "POST" }); toast("正在重启…"); }
    catch (e) { toast(e.message, "err"); }
  },
  async "mode-seg"(d) { await saveSettings({ mode: d.mode }); toast(d.mode === "safe" ? "已切换到安全路由（仅可信渠道）" : "已切换到智能路由"); },
  async "host-seg"(d) { await saveSettings({ server: { host: d.host } }); },
  "provider-add"() { providerModal(null); },
  "provider-edit"(d) { const p = (cfg().providers || []).find(x => x.id === d.id); if (p) providerModal(p); },
  async "provider-del"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.id);
    if (!p) return;
    if (!(await confirmDlg("删除渠道「" + p.name + "」？", "该渠道勾选的调度模型会一并移除。", "删除"))) return;
    try { await api("/api/providers/" + p.id, { method: "DELETE" }); toast("已删除"); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  },
  async "provider-refresh"(d) {
    toast("正在测试连接并获取模型列表…");
    try {
      const r = await api(`/api/providers/${d.id}/refresh`, { method: "POST" });
      if (r.ok) toast(`连接正常，获取到 ${r.models.length} 个模型`);
      else toast("连接失败：" + r.error, "err");
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
  "cd-clear"() { api("/api/cooldowns/clear", { method: "POST", body: "{}" }).then(() => { toast("冷却池已清空"); refresh(); }); },
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
        toast("日志已导出");
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
        toast("配置已导出");
      });
  },
  "cfg-import"() { $("#import-file").click(); },
  "open-promo"() {
    api("/api/open-url", { method: "POST", body: JSON.stringify({ url: "https://aifangan.top" }) })
      .catch(() => toast("打开失败", "err"));
  },
  "sponsor-open"() {
    toast("赞助页地址预留位，后续在代码中替换为你的收款页链接");
  },
  "sponsor-copy"(d) { copyText(d.copy || "https://example.com/sponsor", "赞助链接已复制"); },
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
      <div class="modal-title">修改上下文长度 — ${esc(m)}</div>
      <div class="modal-msg">当前：${curVal ? fmtCtx(curVal) + (cur[1] ? "（渠道标注）" : "（推测）") : "未知"}</div>
      <div class="form-grid">
        <div class="form-item">
          <label>上下文长度（tokens）</label>
          <select id="ctx-sel">
            ${opts.map(v => `<option value="${v}" ${v === curVal ? "selected" : ""}>${v === 0 ? "未知" : fmtCtx(v)}${v === 0 ? "" : " tokens"}</option>`).join("")}
          </select>
        </div>
        <div class="form-item">
          <label>或手动输入</label>
          <input type="number" id="ctx-input" min="0" max="2000000" placeholder="例如 131072" value="${curVal || ""}">
        </div>
      </div>
      <div class="modal-btns"><button class="btn btn-plain" id="ctx-cancel">取消</button><button class="btn btn-primary" id="ctx-save">保存</button></div>`);
    $("#ctx-sel").onchange = e => { $("#ctx-input").value = e.target.value; };
    $("#ctx-cancel").onclick = closeModal;
    $("#ctx-save").onclick = async () => {
      const v = parseInt($("#ctx-input").value || "0", 10);
      if (v < 0 || v > 2000000) { toast("上下文长度需在 0–2000000 之间", "err"); return; }
      if (!p.model_ctx) p.model_ctx = {};
      p.model_ctx[m] = [v, true]; // 手动标注 = exact
      closeModal();
      render();
      try {
        await api("/api/providers/" + p.id, { method: "PUT", body: JSON.stringify({ model_context: p.model_ctx }) });
        toast("上下文长度已更新");
      } catch (e) { toast(e.message, "err"); refresh(); }
    };
  },
  "modal-backdrop"() { closeModal(); },
  "provider-ctx"(d) {
    const p = (cfg().providers || []).find(x => x.id === d.id);
    if (!p) return;
    const models = (p.fetched_models && p.fetched_models.length ? p.fetched_models : p.sched_models) || [];
    if (!models.length) { toast("该渠道还没有模型，请先获取模型列表", "err"); return; }
    const rows = models.map(m => {
      const cur = (p.model_ctx || {})[m] || (p.model_context || {})[m] || [0, false];
      const v = cur[0] || 0;
      return `
      <div class="form-item">
        <label>${esc(m)}</label>
        <input type="number" min="0" max="2000000" data-ctx-input="${esc(m)}" placeholder="0 = 未知" value="${v || ""}">
      </div>`;
    }).join("");
    openModal(`
      <div class="modal-title">模型上下文（tokens）— ${esc(p.name)}</div>
      <div class="modal-msg">每个模型填一个数：131072 = 128K。留空或 0 = 未知，网关会自动推测。常用：32768=32K，65536=64K，131072=128K，262144=256K，1048576=1M。</div>
      <div class="form-grid" style="max-height:46vh;overflow:auto">${rows}</div>
      <div class="modal-btns"><button class="btn btn-plain" id="pcx-cancel">取消</button><button class="btn btn-primary" id="pcx-save">保存</button></div>`);
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
        toast("模型上下文已保存");
        await refresh();
      } catch (e) { toast(e.message, "err"); refresh(); }
    };
  },
};

const CHANGES = {
  async "autostart"(d, el) {
    try {
      const r = await api("/api/autostart", { method: "POST", body: JSON.stringify({ enabled: el.checked }) });
      if (r.ok !== false) toast(el.checked ? "已开启开机自启（后台无界面模式）" : "已关闭开机自启");
      else { toast(r.error || "设置失败", "err"); el.checked = !el.checked; }
    } catch (e) { toast(e.message, "err"); el.checked = !el.checked; }
  },
  "provider-enabled"(d, el) {
    api("/api/providers/" + d.id, { method: "PUT", body: JSON.stringify({ enabled: el.checked }) })
      .then(async () => { toast(el.checked ? "渠道已启用" : "渠道已停用"); await refresh(); })
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
    toast(`智能体模型名已设为「${d.v}」`);
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
    if (!v || v < 1 || v > 65535) { toast("端口范围 1–65535", "err"); render(); return; }
    if (v === cfg().server.port) return;
    if (!(await confirmDlg("更换监听端口？", "将端口改为 " + v + "，保存后需要重启程序生效。", "更换"))) { render(); return; }
    try { await api("/api/server/set-port", { method: "POST", body: JSON.stringify({ port: v }) }); toast("端口已保存为 " + v + "，重启后生效"); await refresh(); }
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
    f.text().then(async t => {
      if (!(await confirmDlg("导入配置？", "将覆盖当前全部渠道与设置（文件含密钥时一并导入）。", "导入", false))) return;
      S.busy = true;
      try { await api("/api/config/import", { method: "POST", body: t }); toast("配置已导入"); await refresh(); }
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


