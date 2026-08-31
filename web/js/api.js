"use strict";
/* ============ API 调用与状态刷新 ============ */
async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (S.key) headers["Authorization"] = "Bearer " + S.key;
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (r.status === 401) { showKeyModal(); throw new Error("__unauthorized"); }
  if (!r.ok) {
    let msg = r.status + " " + r.statusText;
    try { const j = await r.json(); msg = (j.error && j.error.message) || j.detail || msg; } catch (e) { }
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

async function refresh(opts = {}) {
  try {
    S.data = await api("/api/state");
    S.err = null;
  } catch (e) {
    if (e.message !== "__unauthorized") S.err = e.message;
  }
  if (S.err && !S.data) { render(); return; }
  if (opts.dynamic) updateDynamic();
  else render();
}

function applyTheme() {
  if (S.theme === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", S.theme);
  localStorage.setItem("gw_theme", S.theme);
}


