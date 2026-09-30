import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { refreshSession, request, tokens } from "./api";
import type { TokenPair } from "./api";

interface StaffSession {
  staffId: string;
  role: string;
}

interface AuthState {
  session: StaffSession | null;
  loading: boolean;
  login: (email: string, password: string, totp?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

function decode(token: string): StaffSession | null {
  try {
    const [, payload] = token.split(".");
    const claims = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof claims.exp === "number" && claims.exp * 1000 < Date.now()) return null;
    return { staffId: claims.sub, role: claims.role };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StaffSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const access = tokens.access();
      const current = access ? decode(access) : null;
      if (current) {
        if (!cancelled) {
          setSession(current);
          setLoading(false);
        }
        return;
      }
      if (tokens.refresh()) {
        const ok = await refreshSession();
        const nextAccess = tokens.access();
        const next = ok && nextAccess ? decode(nextAccess) : null;
        if (!cancelled) setSession(next);
      }
      if (!cancelled) setLoading(false);
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      session,
      loading,
      async login(email, password, totp) {
        const pair = await request<TokenPair>("/v1/admin/auth/login", {
          method: "POST",
          body: { email, password, totp_code: totp || null },
          retry: false,
        });
        tokens.save(pair);
        setSession(decode(pair.access_token));
      },
      async logout() {
        const refresh = tokens.refresh();
        if (refresh) {
          await request<void>("/v1/admin/auth/logout", {
            method: "POST",
            body: { refresh_token: refresh },
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
