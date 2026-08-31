"use strict";
/* ============ 拖拽排序逻辑 ============ */
let D = null;
function _ghost(text) {
  let g = document.getElementById("drag-ghost");
  if (!g) {
    g = document.createElement("div");
    g.id = "drag-ghost";
    g.style.cssText = "position:fixed;z-index:300;pointer-events:none;transform:translate(-50%,-50%);" +
      "background:var(--accent);color:#fff;font-size:13px;font-weight:600;padding:6px 14px;" +
      "border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.3);white-space:nowrap;" +
      "opacity:.95;letter-spacing:.3px;";
    document.body.appendChild(g);
  }
  g.textContent = text;
  return g;
}
function _clearMarks() {
  $$(".drop-before, .drop-after, .drop-into").forEach(x => x.classList.remove("drop-before", "drop-after", "drop-into"));
}
function _highlight(x, y) {
  _clearMarks();
  const el = document.elementFromPoint(x, y);
  if (!el) return;
  if (D.kind === "card") {
    const head = el.closest("[data-drag]");
    const sec = el.closest("[data-tier]");
    if (head && head.dataset.drag !== D.id) {
      const r = head.getBoundingClientRect();
      D.place = y < r.top + r.height / 2 ? "before" : "after";
      head.classList.add(D.place === "before" ? "drop-before" : "drop-after");
    } else if (!head && sec) {
      D.place = "after";
      sec.classList.add("drop-into");
    } else { D.place = null; }
  } else {
    const chip = el.closest('[data-mdrag][data-pid="' + D.pid + '"]');
    if (chip && chip.dataset.mdrag !== D.id) {
      const r = chip.getBoundingClientRect();
      D.place = x < r.x + r.width / 2 ? "before" : "after";
      D.lastChip = chip.dataset.mdrag; D.lastPlace = D.place;
      chip.classList.add(D.place === "before" ? "drop-before" : "drop-after");
    } else { D.place = null; }
  }
}
function _scrollLoop() {
  if (!D || !D.started) return;
  const m = 60, h = window.innerHeight;
  if (D.lastY != null) {
    if (D.lastY < m) window.scrollBy(0, -Math.round(5 + 18 * (m - D.lastY) / m));
    else if (D.lastY > h - m) window.scrollBy(0, Math.round(5 + 18 * (D.lastY - (h - m)) / m));
  }
  _highlight(D.lastX, D.lastY);
  setTimeout(_scrollLoop, 16);
}
document.addEventListener("mousedown", e => {
  if (e.button !== 0) return;
  const el = e.target;
  if (el.closest("input, textarea, select, button, a, .dd")) return;
  if (el.closest("label")) return;
  const chip = el.closest("[data-mdrag]");
  if (chip) {
    e.preventDefault();
    D = { kind: "model", pid: chip.dataset.pid, id: chip.dataset.mdrag, el: chip,
          sx: e.clientX, sy: e.clientY };
    return;
  }
  if (el.closest(".chips")) return;
  const head = el.closest("[data-drag]");
  if (head) D = { kind: "card", id: head.dataset.drag, el: head, sx: e.clientX, sy: e.clientY };
});
let _lastMove = 0;
const MOVE_THROTTLE = 16; // ~60fps

document.addEventListener("mousemove", e => {
  if (!D) return;
  const now = performance.now();
  if (now - _lastMove < MOVE_THROTTLE) return;
  _lastMove = now;

  if (!D.started) {
    if (Math.hypot(e.clientX - D.sx, e.clientY - D.sy) < 6) return;
    D.started = true;
    D.el.classList.add("dragging");
    const name = D.kind === "card"
      ? (((D.el.querySelector(".provider-title") || {}).childNodes || [])[0] || { textContent: t('tier_channel') }).textContent.trim()
      : D.id;
    D.ghost = _ghost(name);
    S.suppressClick = true;
    setTimeout(() => { S.suppressClick = false; }, 120);
    requestAnimationFrame(_scrollLoop);
  }
  e.preventDefault();
  D.lastX = e.clientX; D.lastY = e.clientY;
  document.body.style.cursor = "grabbing";
  D.ghost.style.left = e.clientX + "px";
  D.ghost.style.top = e.clientY + "px";
  _highlight(e.clientX, e.clientY);
}, { passive: false });
function _cancelDrag() {
  if (!D) return;
  const d = D; D = null;
  if (d.ghost) d.ghost.remove();
  document.body.style.cursor = "";
  d.el.classList.remove("dragging");
  _clearMarks();
  if (d.started) render();
}
window.addEventListener("blur", () => _cancelDrag());

document.addEventListener("mouseup", e => {
  if (!D) return;
  const d = D; D = null;
  if (d.ghost) d.ghost.remove();
  document.body.style.cursor = "";
  d.el.classList.remove("dragging");
  _clearMarks();
  if (!d.started) return;
  e.preventDefault();
  S.suppressClick = true;
  setTimeout(() => { S.suppressClick = false; }, 120);
  const el = document.elementFromPoint(e.clientX, e.clientY);
  if (d.kind === "model") {
    const foreign = el && el.closest ? el.closest("[data-mdrag]") : null;
    if (foreign && foreign.dataset.pid !== d.pid) {
      toast(t('drag_model_err'), "err");
      render();
      return;
    }
    const chip = el && el.closest ? el.closest('[data-mdrag][data-pid="' + d.pid + '"]') : null;
    if (chip && chip.dataset.mdrag !== d.id) { handleChipDrop(d.pid, d.id, chip.dataset.mdrag, d.place || "before"); return; }
    if (d.lastChip && d.lastChip !== d.id) {
      handleChipDrop(d.pid, d.id, d.lastChip, d.lastPlace || "before");
      return;
    }
    const container = el && el.closest ? el.closest(".chips") : null;
    const samePid = container ? [...container.querySelectorAll('[data-mdrag][data-pid="' + d.pid + '"]')] : [];
    if (container && samePid.length) {
      let target = null, placed = "after";
      for (const c of samePid) {
        const r = c.getBoundingClientRect();
        if (e.clientY < r.y) { target = c.dataset.mdrag; placed = "before"; break; }
      }
      if (!target) target = samePid[samePid.length - 1].dataset.mdrag;
      if (target !== d.id) { handleChipDrop(d.pid, d.id, target, placed); return; }
    }
    render();
  } else {
    const head = el && el.closest ? el.closest("[data-drag]") : null;
    const sec = el && el.closest ? el.closest("[data-tier]") : null;
    if (head && head.dataset.drag === d.id) return;
    if (!head && !sec) { render(); return; }
    const targetId = head ? head.dataset.drag : null;
    const tierEl = head ? head.closest("[data-tier]") : sec;
    handleDrop(d.id, targetId, tierEl ? parseInt(tierEl.dataset.tier, 10) : null,
               targetId ? (d.place || "before") : "after");
  }
});

const _chipDropChain = {};
async function _putSched(pid) {
  const prev = _chipDropChain[pid] || Promise.resolve();
  const run = prev.then(async () => {
    const cur = (cfg().providers || []).find(x => x.id === pid);
    if (!cur) return true;
    await api("/api/providers/" + pid, { method: "PUT", body: JSON.stringify({ sched_models: cur.sched_models || [] }) });
    return true;
  });
  _chipDropChain[pid] = run.catch(() => { });
  try {
    await run;
    return true;
  } catch (e) {
    toast(t('save_fail_prefix') + e.message, "err");
    try {
      const st = await api("/api/state");
      const sp = (st.config.providers || []).find(x => x.id === pid);
      const lp = (cfg().providers || []).find(x => x.id === pid);
      if (lp && sp) lp.sched_models = (sp.sched_models || []).slice();
      render();
    } catch (_) { }
    return false;
  }
}

async function handleChipDrop(pid, srcModel, targetModel, placement = "before") {
  const p = (cfg().providers || []).find(x => x.id === pid);
  if (!p) return;
  const s = p.sched_models = p.sched_models || [];
  const i = s.indexOf(srcModel);
  if (i >= 0) s.splice(i, 1);
  const j = s.indexOf(targetModel);
  if (j < 0) s.push(srcModel);
  else if (placement === "after") s.splice(j + 1, 0, srcModel);
  else s.splice(j, 0, srcModel);
  render();
  if (await _putSched(pid)) toast(t('model_sched_order_updated'));
}

async function handleDrop(srcId, targetId, toTier, placement = "before") {
  const ps = cfg().providers || [];
  const byId = Object.fromEntries(ps.map(p => [p.id, p]));
  if (!byId[srcId]) return;
  const order = [];
  for (let ti2 = 0; ti2 < 3; ti2++) for (const p of ps) if (tierOf(p) === ti2) order.push(p.id);
  const si = order.indexOf(srcId);
  if (si >= 0) order.splice(si, 1);
  let destTier = toTier;
  if (targetId) {
    let ti = order.indexOf(targetId);
    if (ti < 0) return;
    if (placement === "after") ti += 1;
    order.splice(ti, 0, srcId);
    if (destTier === null || destTier === undefined) destTier = tierOf(byId[targetId]);
  } else if (destTier === null || destTier === undefined) return;
  const tiers = [[], [], []];
  for (const id of order) tiers[id === srcId ? destTier : tierOf(byId[id])].push(id);
  S.busy = true;
  try {
    await api("/api/providers/reorder", { method: "POST", body: JSON.stringify({ tiers }) });
    toast(t('sched_order_updated'));
    await refresh();
  } catch (e) { toast(e.message, "err"); refresh(); } finally { S.busy = false; }
}


