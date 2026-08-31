"use strict";
/* ============ 调度集合工具 ============ */
function schedProviders() {
  const safe = cfg().mode === "safe";
  return (cfg().providers || [])
    .filter(p => p.enabled && (p.sched_models || []).length && (!safe || (p.trusted ?? p.domestic)))
    .sort((a, b) => (a.priority || 99) - (b.priority || 99));
}
function schedUnion() {
  const set = new Set();
  for (const p of schedProviders()) (p.sched_models || []).forEach(m => set.add(m));
  return [...set];
}
function ctxOf(p, m) {
  const e = (p.model_ctx || {})[m];
  if (e) return { ctx: e[0], exact: true };
  return { ctx: 0, exact: false };
}
function ctxBadge(p, m) {
  const { ctx, exact } = ctxOf(p, m);
  if (!ctx) return `<span class="ctx unknown" title="${t("ctx_unknown")}">?</span>`;
  return `<span class="ctx ${exact ? "" : "guess"}" title="${exact ? t("ctx_exact") : t("ctx_guess")}">${exact ? "" : "~"}${fmtCtx(ctx)}</span>`;
}


