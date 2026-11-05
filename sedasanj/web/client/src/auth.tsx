import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { refreshSession, request, tokens } from "./api";
import type { TokenPair, User } from "./types";

interface Session {
  userId: string;
  tenantId: string;
  role: string;
  panelPermissions: string[] | null;
}

interface AuthState {
  session: Session | null;
  loading: boolean;
  login: (identifier: string, password: string, totp?: string) => Promise<void>;
  acceptSession: (pair: TokenPair) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

function decode(token: string): Session | null {
  try {
    const [, payload] = token.split(".");
    const claims = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof claims.exp === "number" && claims.exp * 1000 < Date.now()) return null;
    return { userId: claims.sub, tenantId: claims.tenant_id, role: claims.role, panelPermissions: Array.isArray(claims.panel_permissions) ? claims.panel_permissions : null };
  } catch {
    return null;
  }
}

async function loadSession(token: string): Promise<Session | null> {
  const current = decode(token);
  if (!current) return null;
  const user = await request<User>("/v1/auth/me");
  return { ...current, role: user.role, panelPermissions: user.effective_panel_permissions ?? [] };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const access = tokens.access();
      const current = access ? await loadSession(access).catch(() => null) : null;
      if (current) {
        if (!cancelled) {
          setSession(current);
          setLoading(false);
        }
        return;
      }
      if (tokens.hasSession()) {
        const ok = await refreshSession();
        const nextAccess = tokens.access();
        const next = ok && nextAccess ? await loadSession(nextAccess).catch(() => null) : null;
        if (!cancelled) setSession(next);
      }
      if (!cancelled) setLoading(false);
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    let inFlight = false;
    async function refreshAccess() {
      const access = tokens.access();
      if (!access || inFlight) return;
      inFlight = true;
      try {
        const next = await loadSession(access);
        if (!cancelled && next) setSession(next);
      } catch { /* The API still enforces access on every request. */ }
      finally { inFlight = false; }
    }
    const timer = window.setInterval(() => void refreshAccess(), 60000);
    const focus = () => void refreshAccess();
    window.addEventListener("focus", focus);
    return () => { cancelled = true; window.clearInterval(timer); window.removeEventListener("focus", focus); };
  }, [session?.userId]);

  const value = useMemo<AuthState>(
    () => ({
      session,
      loading,
      acceptSession(pair) {
        tokens.save(pair);
        setLoading(true);
        void loadSession(pair.access_token).then(setSession).catch(() => setSession(null)).finally(() => setLoading(false));
      },
      async login(identifier, password, totp) {
        const pair = await request<TokenPair>("/v1/auth/login", {
          method: "POST",
          body: { identifier, password, totp_code: totp || null },
          retry: false,
        });
        tokens.save(pair);
        setSession(await loadSession(pair.access_token));
      },
      async logout() {
        // The cookie carries the refresh token; the server revokes it and expires the cookie.
        if (tokens.hasSession()) {
          await request<void>("/v1/auth/logout", {
            method: "POST",
            body: { refresh_token: "" },
            retry: false,
          }).catch(() => undefined);
        }
        tokens.clear();
        setSession(null);
      },
    }),
    [session, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth outside AuthProvider");
  return context;
}

export const CAN_HEAR_AUDIO = ["org_admin", "operator"];
export const CAN_UPLOAD_CALLS = ["org_admin", "operator"];
export const CAN_EDIT_TASKS = ["org_admin", "operator"];
/** Roles that may rename speakers, reanalyze and retry meetings; a viewer only reads meetings they own. */
export const CAN_MANAGE_MEETINGS = ["org_admin", "operator"];
export const ROLE_LABELS: Record<string, string> = {
  org_admin: "مدیر سازمان",
  operator: "اپراتور",
  viewer: "بیننده",
};

export function isOrgAdmin(role: string | undefined): boolean {
  return role === "org_admin";
}

export function isOperator(role: string | undefined): boolean {
  return role === "operator";
}
