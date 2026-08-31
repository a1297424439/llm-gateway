"use strict";
/* ============ 工具函数 ============ */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = ts => { const d = new Date(ts * 1000); return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`; };
const fmtDur = s => { s = Math.floor(s); if (s < 60) return s + " " + t('dur_s'); if (s < 3600) return Math.floor(s / 60) + " " + t('dur_m') + " " + (s % 60) + " " + t('dur_s'); return Math.floor(s / 3600) + " " + t('dur_h') + " " + Math.floor((s % 3600) / 60) + " " + t('dur_m'); };
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
function copyText(text, tip) {
  const done = () => toast(tip || t('common_copied'));
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else fallbackCopy(text, done);
}
function fallbackCopy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { toast(t('copy_fail'), "err"); }
  ta.remove();
}


