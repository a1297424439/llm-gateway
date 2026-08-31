"use strict";
/* ============ 全局状态 ============ */
const S = {
  data: null, presets: [], view: "dashboard",
  key: localStorage.getItem("gw_key") || "",
  theme: localStorage.getItem("gw_theme") || "auto",
  logFilter: "all", expandedProviders: new Set(), expandedLogs: new Set(),
  busy: false, err: null, keyVisible: false,
  collapsedTiers: JSON.parse(localStorage.getItem("gw_collapsed") || "[]"),
  dragId: null, autostart: false,
};
const cfg = () => (S.data && S.data.config) || { server: {}, routing: {}, cooldown: {}, providers: [], aliases: [] };


