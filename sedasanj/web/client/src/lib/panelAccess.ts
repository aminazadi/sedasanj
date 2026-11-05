export interface PanelSession { role: string; panelPermissions?: readonly string[] | null }
export interface PanelAccessOption { key: string; label: string; roles: string[]; assignable: boolean }

export function hasPanelAccess(session: PanelSession | null | undefined, section: string): boolean {
  return Boolean(session && (session.panelPermissions == null || session.panelPermissions.includes(section)));
}

export const SETTINGS_ACCESS: Record<string, string> = {
  scoring: "scoring_settings", ai: "ai_settings", kpi: "kpi_settings", users: "users",
  integrations: "integrations", data: "data",
};

export function canVisitPanel(session: PanelSession | null | undefined, path: string, search = ""): boolean {
  if (path === "/profile" || /^(\/help|\/about|\/contact|\/terms|\/privacy|\/cancellation)(\/|$)/.test(path)) return true;
  if (path.startsWith("/account-settings/data")) return hasPanelAccess(session, "data");
  if (path === "/account-settings" || path === "/kpi-settings") {
    const tab = path === "/kpi-settings" ? "kpi" : new URLSearchParams(search).get("tab");
    return tab && SETTINGS_ACCESS[tab] ? hasPanelAccess(session, SETTINGS_ACCESS[tab])
      : Object.values(SETTINGS_ACCESS).some(section => hasPanelAccess(session, section));
  }
  const sections: Array<[string, string]> = [
    ["/", "dashboard"], ["/calls", "calls"], ["/voicemails", "calls"],
    ["/meetings", "meetings"], ["/contacts", "contacts"], ["/extensions", "extensions"],
    ["/tasks", "tasks"], ["/assistant", "assistant"], ["/scheduled-reports", "reports"],
    ["/operator-scores", "scores"], ["/account", "billing"], ["/checkout", "billing"],
    ["/billing", "billing"], ["/payment-result", "billing"], ["/install", "setup"],
    ["/freepbx-servers", "pbx_servers"], ["/module-changelog", "releases"], ["/api-docs", "api_docs"],
  ];
  const section = sections.find(([prefix]) => path === prefix || (prefix !== "/" && path.startsWith(prefix + "/")))?.[1];
  return section ? hasPanelAccess(session, section) : true;
}

export function panelHome(session: PanelSession): string {
  return ["/", "/calls", "/meetings", "/contacts", "/extensions", "/tasks", "/assistant",
    "/scheduled-reports", "/operator-scores", "/account", "/account-settings", "/install",
    "/freepbx-servers", "/module-changelog", "/api-docs"].find(path => canVisitPanel(session, path)) ?? "/profile";
}
