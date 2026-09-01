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
  if (!ctx) return '<span class="ctx unknown" title="上下文未知：可手动勾选，自行判断">?</span>';
  return `<span class="ctx ${exact ? "" : "guess"}" title="${exact ? "渠道标注的上下文" : "按模型家族推测的上下文"}">${exact ? "" : "~"}${fmtCtx(ctx)}</span>`;
}


