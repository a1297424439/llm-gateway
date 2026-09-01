"use strict";
/* ============ 工具函数 ============ */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = ts => { const d = new Date(ts * 1000); return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`; };
const fmtDur = s => { s = Math.floor(s); if (s < 60) return s + " 秒"; if (s < 3600) return Math.floor(s / 60) + " 分 " + (s % 60) + " 秒"; return Math.floor(s / 3600) + " 时 " + Math.floor((s % 3600) / 60) + " 分"; };
const maskKey = k => k ? k.slice(0, 8) + "••••••••••••" + k.slice(-4) : "—";
function hashStr(s) { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return String(h); }
function setText(sel, t) { const el = $(sel); if (el && el.textContent !== String(t)) el.textContent = String(t); }
function fmtCtx(ctx) { return ctx >= 1000000 ? Math.round(ctx / 1000000) + "M" : Math.round(ctx / 1000) + "K"; }

function toast(msg, type = "ok") {
  const root = $("#toast-root");
  root.innerHTML = `<div class="toast ${type === "err" ? "err" : ""}">${esc(msg)}</div>`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { root.innerHTML = ""; }, 2400);
}
function copyText(t, tip = "已复制") {
  const done = () => toast(tip);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t).then(done).catch(() => fallbackCopy(t, done));
  } else fallbackCopy(t, done);
}
function fallbackCopy(t, done) {
  const ta = document.createElement("textarea");
  ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { toast("复制失败", "err"); }
  ta.remove();
}


