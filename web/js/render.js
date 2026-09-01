"use strict";
/* ============ 渲染骨架 ============ */
let cdHash = "", logHash = "", dashKey = "";
function render() {
  if (typeof D !== "undefined" && D) _cancelDrag();
  renderTop();
  renderTabbar();
  const v = $("#view");
  if (S.err && !S.data) {
    v.innerHTML = `<div class="view-title fade-in">概览</div><div class="card card-pad fade-in"><div class="empty"><div class="big">无法连接网关</div><div class="hint">${esc(S.err)}</div></div></div>`;
    return;
  }
  const banner = S.data && S.data.pending_restart
    ? `<div class="banner"><div class="banner-inner"><span>监听地址/端口已修改，重启程序后生效</span><button class="btn btn-sm btn-primary" data-act="server-restart">立即重启</button></div></div>`
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
      if (cb) cb.innerHTML = cds.length ? '<button class="btn btn-sm btn-plain" data-act="cd-clear">全部恢复</button>' : "";
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
  b.textContent = mode === "safe" ? "安全路由" : "智能路由";
  b.className = "badge " + (mode === "safe" ? "badge-green" : "badge-blue");
}
function renderTabbar() {
  $("#tabbar").innerHTML = TABS.map(t =>
    `<button class="tab ${S.view === t.id ? "active" : ""}" data-act="nav" data-view="${t.id}">${t.icon}<span>${t.name}</span></button>`).join("");
}

/* ============ 辅助 HTML 生成 ============ */
function logListHtml() {
  let logs = (S.data && S.data.logs) || [];
  if (S.logFilter !== "all") logs = logs.filter(l => S.logFilter === "ok" ? l.ok : !l.ok);
  if (!logs.length) return `<div class="empty">暂无请求记录</div>`;
  return logs.map(l => {
    const dot = l.ok ? "ok" : "fail";
    const route = l.provider ? `${esc(l.provider)} / ${esc(l.model || "")}` : "未命中任何渠道";
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
  if (!cds.length) return `<div class="empty">冷却池为空，所有渠道健康</div>`;
  return cds.map(cd => `
        <div class="cd-row">
          <span class="cd-dot"></span>
          <div class="row-main">
            <div class="label mono" style="font-size:13px">${esc(cd.provider)} · ${esc(cd.model)}${cd.provider_level ? ` <span class="hint" style="font-size:10px">${cd.ctype === "rate" ? "限流冷却" : "额度冷却"}</span>` : ""}</div>
            <div class="desc">已失败 ${cd.fails} 次，${fmtDur(cd.remaining)}后自动恢复</div>
            ${cd.last_error ? `<div class="desc mono" style="font-size:11px;word-break:break-all">${esc(cd.last_error)}</div>` : ""}
          </div>
          <button class="btn btn-sm btn-plain" data-act="cd-clear-one" data-key="${esc(cd.key)}">立即恢复</button>
        </div>`).join("");
}

function logDetail(l) {
  const parts = [];
  if (l.error) parts.push(`<div class="hint" style="color:var(--red)">错误：${esc(l.error)}</div>`);
  if (Array.isArray(l.attempts) && l.attempts.length) {
    parts.push('<div class="code">' + esc(l.attempts.map(a =>
      `→ ${a.provider || "?"} / ${a.model || "?"}${a.skipped ? "  [跳过:" + a.skipped + "]" : ""}${a.error ? "  [失败 HTTP " + (a.status || "?") + ": " + a.error + "]" : ""}${a.cooldown ? "  [已入冷却池]" : ""}`
    ).join("\n")) + '</div>');
  }
  return parts.join("") || '<div class="hint">无详细信息</div>';
}

function buildCurl(url, key, model) {
  return `curl ${url}/chat/completions \\\n  -H "Authorization: Bearer ***" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "model": "${model || "模型名"}",\n    "messages": [{"role": "user", "content": "你好"}]\n  }'`;
}

function modeDesc(m) {
  return m === "safe"
    ? "安全路由（信任路由）：仅使用你标记为「可信」的渠道转发请求，其余渠道一律不调度。"
    : "智能路由：按档位优先级自动调度全部启用渠道，失败自动切换到下一档，并加入冷却池。";
}

function tierOf(p) {
  const pr = p.priority || 1;
  return pr < 10 ? 0 : pr < 20 ? 1 : 2;
}
function chipHtml(p, m) {
  const on = (p.sched_models || []).includes(m);
  const cls = on ? "selected" : "off";
  const tip = on ? "拖拽调整顺序 · 点击取消调度"
            : "拖拽 = 勾选并放到该位置 · 点击 = 勾选/取消";
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
    <div class="pc-top" data-drag="${esc(p.id)}" title="按住拖拽调整档位与顺序（最上面最优先）">
      <span class="drag-dot">⠿</span>
      <div class="row-main">
        <div class="provider-title">${esc(p.name)}
          <span class="badge ${(p.trusted ?? p.domestic) ? "badge-green" : "badge-gray"}">${(p.trusted ?? p.domestic) ? "可信渠道" : "普通渠道"}</span>
          <span class="badge badge-blue">${p.adapter === "anthropic" ? "Anthropic" : "OpenAI 兼容"}</span>
          ${p.enabled ? "" : '<span class="badge badge-orange">已停用</span>'}
        </div>
        <div class="provider-url">${esc(p.base_url)}</div>
      </div>
      <span class="badge badge-blue" style="flex:none">已选 ${sel.length}/${all.length}</span>
      <label class="switch"><input type="checkbox" data-change="provider-enabled" data-id="${esc(p.id)}" ${p.enabled ? "checked" : ""}><span class="knob"></span></label>
    </div>
    ${test ? `<div class="provider-meta"><span class="badge ${test.ok ? "badge-green" : "badge-red"}">${test.ok ? "✓" : "✕"} ${esc(test.detail || "")}</span></div>` : ""}
    <div class="chips">
      <button class="chip chip-add" data-act="provider-refresh" data-id="${esc(p.id)}">⟳ 刷新</button>
      <button class="chip chip-add" data-act="model-add" data-id="${esc(p.id)}">＋ 手动添加</button>
      ${all.length ? `<button class="chip chip-add" data-act="chip-all" data-id="${esc(p.id)}">全选</button>
      <button class="chip chip-add" data-act="chip-none" data-id="${esc(p.id)}">清空</button>` : ""}
      ${selOrdered.length ? `<span class="chip sep sel-sep">已选（拖拽调整顺序）</span>` + selOrdered.map(m => chipHtml(p, m)).join("") : ""}
      ${restShown.length ? `<span class="chip sep">— 未参与调度 —</span>` + restShown.map(m => chipHtml(p, m)).join("") : ""}
      ${hiddenCount > 0 ? `<span class="chip chip-add" data-act="provider-models" data-id="${esc(p.id)}">${expanded ? "收起" : "…" + hiddenCount + " 更多"}</span>` : ""}
    </div>
    <div class="row pc-foot">
      <div class="btn-row">
        <button class="btn btn-sm btn-plain" data-act="provider-edit" data-id="${esc(p.id)}">编辑</button>
        <button class="btn btn-sm btn-plain" data-act="provider-ctx" data-id="${esc(p.id)}">模型上下文</button>
        <button class="btn btn-sm btn-danger" data-act="provider-del" data-id="${esc(p.id)}">删除</button>
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
function confirmDlg(title, msg, okText = "确定", danger = true) {
  return new Promise(res => {
    openModal(`<div class="modal-title">${esc(title)}</div><div class="modal-msg">${esc(msg)}</div>
      <div class="modal-btns"><button class="btn btn-plain" id="cfm-no">取消</button>
      <button class="btn ${danger ? "btn-danger" : "btn-primary"}" id="cfm-yes">${esc(okText)}</button></div>`);
    $("#cfm-no").onclick = () => { closeModal(); res(false); };
    $("#cfm-yes").onclick = () => { closeModal(); res(true); };
  });
}
function showKeyModal() {
  openModal(`<div class="modal-title">需要访问密钥</div>
    <div class="modal-msg">当前不是从本机访问，请输入网关 API Key（sk-lg-…）。</div>
    <div class="form-grid"><div class="form-item"><input type="password" id="gwkey-input" placeholder="sk-lg-..." autocomplete="off"></div></div>
    <div class="modal-btns"><button class="btn btn-plain" id="gwkey-cancel">取消</button><button class="btn btn-primary" id="gwkey-ok">保存并连接</button></div>`);
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
    <div class="modal-title">${existing ? "编辑渠道" : "添加渠道"}</div>
    <div class="form-grid">
      <div class="form-item">
        <label>从预设填充（可选）</label>
        <select id="pf-preset">
          <option value="">— 自定义 / 手动填写 —</option>
          <optgroup label="可信渠道（安全路由可用）">${dom.map((p, i) => `<option value="d${i}">${esc(p.name)}</option>`).join("")}</optgroup>
          <optgroup label="其他渠道">${intl.map((p, i) => `<option value="i${i}">${esc(p.name)}</option>`).join("")}</optgroup>
        </select>
      </div>
      <div class="form-item"><label>渠道名称</label><input id="pf-name" placeholder="例如：DeepSeek 官方" value="${esc(existing ? existing.name : "")}"></div>
      <div class="form-item"><label>Base URL（一般以 /v1 或 /compatible-mode/v1 结尾）</label><input id="pf-url" placeholder="https://api.example.com/v1" value="${esc(existing ? existing.base_url : "")}"></div>
      <div class="form-item"><label>API Key</label><input id="pf-key" type="password" placeholder="sk-..." autocomplete="off" value="${esc(existing ? existing.api_key : "")}"></div>
      <div class="form-item"><label>协议适配器</label>
        <select id="pf-adapter">
          <option value="openai" ${!existing || existing.adapter !== "anthropic" ? "selected" : ""}>OpenAI 兼容（绝大多数服务）</option>
          <option value="anthropic" ${existing && existing.adapter === "anthropic" ? "selected" : ""}>Anthropic 原生</option>
        </select>
      </div>
      <div class="form-item"><div class="rowlike"><span><b style="font-size:13.5px">可信渠道</b><div class="hint">标记为可信后可在安全路由（信任路由）模式下被调度，由你决定信任哪些渠道</div></span>
        <label class="switch"><input type="checkbox" id="pf-trusted" ${existing && (existing.trusted ?? existing.domestic) ? "checked" : ""}><span class="knob"></span></label></div></div>
      <div class="form-item"><label>备注（可选）</label><input id="pf-note" value="${esc(existing ? existing.note || "" : "")}"></div>
    </div>
    <div class="modal-btns"><button class="btn btn-plain" id="pf-cancel">取消</button><button class="btn btn-primary" id="pf-save">${existing ? "保存" : "添加"}</button></div>`);
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
    if (!body.name || !body.base_url.startsWith("http")) { toast("名称与合法的 Base URL 必填", "err"); return; }
    S.busy = true;
    try {
      if (existing) await api("/api/providers/" + existing.id, { method: "PUT", body: JSON.stringify(body) });
      else await api("/api/providers", { method: "POST", body: JSON.stringify(body) });
      closeModal(); toast(existing ? "已保存" : "渠道已添加");
      await refresh();
    } catch (e) { toast(e.message, "err"); } finally { S.busy = false; }
  };
}
function modelAddModal(p) {
  openModal(`<div class="modal-title">手动添加模型 — ${esc(p.name)}</div>
    <div class="form-grid"><div class="form-item">
      <label>模型名（与上游一致；多个可用逗号分隔批量添加）</label>
      <input id="ma-name" placeholder="例如 glm-5.3-flash">
      <div class="hint" style="margin-top:6px">添加后标签为未勾选状态，点击标签即可参与调度</div>
    </div></div>
    <div class="modal-btns"><button class="btn btn-plain" id="ma-cancel">取消</button><button class="btn btn-primary" id="ma-ok">添加</button></div>`);
  $("#ma-cancel").onclick = closeModal;
  $("#ma-ok").onclick = async () => {
    const raw = $("#ma-name").value.trim();
    if (!raw) { toast("请输入模型名", "err"); return; }
    const names = raw.split(/[,，\s]+/).filter(Boolean);
    S.busy = true;
    try {
      for (const n of names) {
        await api(`/api/providers/${p.id}/models-add`, { method: "POST", body: JSON.stringify({ model: n }) });
      }
      closeModal(); toast(`已添加 ${names.length} 个模型`);
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
  openModal(`<div class="modal-title">关闭窗口</div>
    <div class="modal-msg">要退出调度中枢，还是把它最小化到托盘继续服务？（Hermes 等客户端只有在程序运行时才能连接）</div>
    <label class="hint" style="display:flex;align-items:center;gap:8px;margin:12px 18px 0;cursor:pointer">
      <input type="checkbox" id="ca-remember" style="width:auto"> 记住我的选择，今后点 ✕ 不再询问
    </label>
    <div class="modal-btns" style="flex-direction:column">
      <button class="btn btn-primary" id="ca-hide" style="height:44px">隐藏到托盘（服务继续运行）</button>
      <button class="btn btn-danger" id="ca-quit" style="height:44px">退出程序</button>
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
    toast("正在退出…");
    try { await api("/api/window/quit", { method: "POST", body: "{}" }); } catch (e) { }
  };
};


