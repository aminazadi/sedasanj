import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { chartDark, chartLight } from "../theme.js";
import type { ChartColors } from "../theme";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "sedasanj:theme-mode";

function storedMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    /* Storage may be unavailable (private mode, blocked cookies). */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

/** Mirrors the inline script in index.html that avoids a flash on load. */
function applyMode(mode: ThemeMode) {
  const root = document.documentElement;
  if (mode === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", mode);
}

interface ThemeState {
  /** The owner's choice: light, dark, or follow the system. */
  mode: ThemeMode;
  /** What "system" currently resolves to, for anything (e.g. a chart) that
   * needs a concrete light/dark color set rather than CSS variables. */
  resolved: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

/** Wrap the app once, near the root, so every page can call `useTheme()`. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(storedMode);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    applyMode(mode);
  }, [mode]);

  useEffect(() => {
    let mql: MediaQueryList;
    try {
      mql = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return;
    }
    const listener = () => setSystemDark(mql.matches);
    mql.addEventListener("change", listener);
    return () => mql.removeEventListener("change", listener);
  }, []);

  function setMode(next: ThemeMode) {
    setModeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* The choice still applies for this tab/session. */
    }
  }

  const resolved: "light" | "dark" = mode === "system" ? (systemDark ? "dark" : "light") : mode;
  const value = useMemo(() => ({ mode, resolved, setMode }), [mode, resolved]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}

/** The chart palette (Recharts/SVG need literal colors, not CSS variables)
 * for whichever mode is actually showing right now. */
export function useChartColors(): ChartColors {
  const { resolved } = useTheme();
  return resolved === "dark" ? chartDark : chartLight;
}
