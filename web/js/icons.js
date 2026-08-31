"use strict";
/* ============ 图标 ============ */
const IC = {
  dash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/></svg>',
  server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="7" rx="2.2"/><rect x="3" y="13" width="18" height="7" rx="2.2"/><circle cx="7.2" cy="7.5" r="1" fill="currentColor" stroke="none"/><circle cx="7.2" cy="16.5" r="1" fill="currentColor" stroke="none"/></svg>',
  route: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="6" cy="5.5" r="2.4"/><circle cx="18" cy="18.5" r="2.4"/><path d="M6 7.9V12a5 5 0 0 0 5 5h4.4"/><path d="M13.5 14.6 15.8 17l-2.3 2.4"/></svg>',
  logs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M8.5 6h11M8.5 12h11M8.5 18h11"/><circle cx="4.2" cy="6" r="1.1" fill="currentColor" stroke="none"/><circle cx="4.2" cy="12" r="1.1" fill="currentColor" stroke="none"/><circle cx="4.2" cy="18" r="1.1" fill="currentColor" stroke="none"/></svg>',
};
const TABS = [
  { id: "dashboard", icon: IC.dash },
  { id: "providers", icon: IC.server },
  { id: "settings", icon: IC.route },
  { id: "logs", icon: IC.logs },
];


