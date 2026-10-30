import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useApp } from "../lib/context.jsx";

export default function Login() {
  const { setUser, branding, reload } = useApp();
  const nav = useNavigate();
  const [step, setStep] = useState("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState({ token: "", methods: [], method: "totp", code: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(null);
  const [setupForm, setSetupForm] = useState({ email: "", username: "", password: "", confirm: "" });
  const b = branding || {};

  useEffect(() => {
    api.get("/api/auth/setup-status").then((r) => setNeedsSetup(r.needs_setup)).catch(() => setNeedsSetup(false));
  }, []);

  async function submitSetup(e) {
    e.preventDefault();
    setErr("");
    if (setupForm.password !== setupForm.confirm) return setErr("Passwords do not match");
    setBusy(true);
    try {
      await api.post("/api/auth/setup", {
        email: setupForm.email, username: setupForm.username, password: setupForm.password,
      });
      await finish(); // setup auto-signs in
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function submitPassword(e) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const r = await api.post("/api/auth/login", { email, password });
      if (r.mfa_required) {
        setMfa((m) => ({ ...m, token: r.mfa_token, methods: r.methods, method: r.methods[0] }));
        setStep("mfa");
      } else {
        await finish();
      }
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function submitMfa(e) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      await api.post("/api/auth/login/mfa", { mfa_token: mfa.token, method: mfa.method, code: mfa.code });
      await finish();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function finish() {
    await reload();
    const me = await api.get("/api/auth/me");
    setUser(me);
    nav("/");
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="card w-full max-w-md p-8">
        <div className="flex items-center gap-3 mb-6">
          {b.logo_light && <img src={b.logo_light} alt="" className="h-9" onError={(e)=>(e.target.style.display="none")} />}
          <div>
            <div className="text-xl font-extrabold">{b.app_name || "Xyberah"}</div>
            <div className="text-xs text-slate-500">{b.tagline}</div>
          </div>
        </div>

        {err && <div className="mb-4 rounded-lg bg-red-50 text-red-700 text-sm px-3 py-2">{err}</div>}

        {needsSetup === null ? (
          <p className="text-slate-500 text-sm">Loading…</p>
        ) : needsSetup ? (
          <form onSubmit={submitSetup} className="space-y-4">
            <div className="rounded-lg bg-violet-50 text-sm px-3 py-2" style={{ color: "var(--brand-primary)" }}>
              Welcome! This is a fresh install. Create the first <b>global administrator</b> account.
            </div>
            <div>
              <label className="label">Admin email</label>
              <input className="input" type="email" value={setupForm.email} autoFocus required
                     onChange={(e) => setSetupForm({ ...setupForm, email: e.target.value })} />
            </div>
            <div>
              <label className="label">Display name (optional)</label>
              <input className="input" value={setupForm.username}
                     onChange={(e) => setSetupForm({ ...setupForm, username: e.target.value })} />
            </div>
            <div>
              <label className="label">Password (min 10 characters)</label>
              <input className="input" type="password" value={setupForm.password} required
                     onChange={(e) => setSetupForm({ ...setupForm, password: e.target.value })} />
            </div>
            <div>
              <label className="label">Confirm password</label>
              <input className="input" type="password" value={setupForm.confirm} required
                     onChange={(e) => setSetupForm({ ...setupForm, confirm: e.target.value })} />
            </div>
            <button className="btn-primary w-full" disabled={busy}>
              {busy ? "Creating…" : "Create admin & sign in"}
            </button>
          </form>
        ) : step === "password" ? (
          <form onSubmit={submitPassword} className="space-y-4">
            <div>
              <label className="label">Email</label>
              <input className="input" type="email" value={email} autoFocus
                     onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div>
              <label className="label">Password</label>
              <input className="input" type="password" value={password}
                     onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <button className="btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
        ) : (
          <form onSubmit={submitMfa} className="space-y-4">
            <p className="text-sm text-slate-600">Two-factor authentication required.</p>
            {mfa.methods.length > 1 && (
              <div className="flex gap-2">
                {mfa.methods.map((m) => (
                  <button type="button" key={m}
                    className={`tab ${mfa.method === m ? "tab-active" : "border border-slate-200"}`}
                    onClick={() => setMfa((x) => ({ ...x, method: m }))}>
                    {m === "totp" ? "Authenticator app" : "Email code"}
                  </button>
                ))}
              </div>
            )}
            <div>
              <label className="label">{mfa.method === "totp" ? "6-digit app code" : "Code emailed to you"}</label>
              <input className="input tracking-widest text-center" value={mfa.code} autoFocus
                     inputMode="numeric" maxLength={6}
                     onChange={(e) => setMfa((x) => ({ ...x, code: e.target.value }))} required />
            </div>
            <button className="btn-primary w-full" disabled={busy}>{busy ? "Verifying…" : "Verify"}</button>
            <button type="button" className="text-xs text-slate-500 w-full" onClick={() => setStep("password")}>
              Back
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
