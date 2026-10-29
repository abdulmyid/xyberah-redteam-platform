import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";

const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

function applyBranding(b) {
  if (!b) return;
  const r = document.documentElement.style;
  r.setProperty("--brand-primary", b.primary);
  r.setProperty("--brand-secondary", b.secondary);
  r.setProperty("--brand-accent", b.accent);
  document.title = b.app_name || "Xyberah";
  if (b.favicon) {
    let link = document.querySelector("link[rel=icon]");
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = b.favicon;
  }
}

export function AppProvider({ children }) {
  const [user, setUser] = useState(null);
  const [branding, setBranding] = useState(null);
  const [loading, setLoading] = useState(true);

  const refreshBranding = useCallback(async () => {
    try {
      const b = await (api.get("/api/branding/me").catch(() => api.get("/api/branding")));
      setBranding(b);
      applyBranding(b);
    } catch {
      /* unauthenticated: public default already themed */
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const me = await api.get("/api/auth/me");
      setUser(me);
    } catch {
      setUser(null);
    }
    // Public branding themes the login page; per-company overrides after login
    try {
      const pub = await api.get("/api/branding");
      setBranding((b) => b || pub);
      applyBranding(pub);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (user) refreshBranding();
  }, [user, refreshBranding]);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout").catch(() => {});
    setUser(null);
  }, []);

  return (
    <AppCtx.Provider value={{ user, setUser, branding, refreshBranding, logout, loading, reload: load }}>
      {children}
    </AppCtx.Provider>
  );
}
