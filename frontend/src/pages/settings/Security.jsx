import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useApp } from "../../lib/context.jsx";

export default function Security() {
  const { user, reload } = useApp();
  const [me, setMe] = useState(user);
  const [setup, setSetup] = useState(null); // {secret, otpauth_uri}
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });

  useEffect(() => { api.get("/api/auth/me").then(setMe); }, []);

  async function beginTotp() {
    setMsg("");
    const r = await api.post("/api/auth/totp/begin");
    setSetup(r);
  }
  async function enableTotp() {
    setMsg("");
    try {
      await api.post("/api/auth/totp/enable", { secret: setup.secret, code });
      setSetup(null); setCode(""); setMsg("Authenticator app enabled.");
      await refresh();
    } catch (e) { setMsg(e.message); }
  }
  async function disableTotp() { await api.post("/api/auth/totp/disable"); await refresh(); }
  async function toggleEmailOtp(on) { await api.post(`/api/auth/email-otp/${on ? "enable" : "disable"}`); await refresh(); }
  async function refresh() { const m = await api.get("/api/auth/me"); setMe(m); reload(); }

  async function changePw(e) {
    e.preventDefault(); setMsg("");
    try { await api.post("/api/auth/password", pw); setPw({ current_password: "", new_password: "" }); setMsg("Password changed."); }
    catch (e) { setMsg(e.message); }
  }

  return (
    <div className="space-y-5 max-w-xl">
      {msg && <div className="rounded-lg bg-slate-100 text-sm px-3 py-2">{msg}</div>}

      <div className="card p-6 space-y-3">
        <h2 className="font-bold text-lg">Authenticator app (TOTP)</h2>
        {me.totp_enabled ? (
          <div className="flex items-center justify-between">
            <span className="chip sev-low">Enabled</span>
            <button className="btn-ghost" onClick={disableTotp}>Disable</button>
          </div>
        ) : setup ? (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Scan this with Google Authenticator, 1Password, etc.</p>
            <img alt="QR" className="border rounded" width="180" height="180"
                 src={`/api/auth/totp/qr?secret=${encodeURIComponent(setup.secret)}`} />
            <p className="text-xs text-slate-500 break-all">Secret: {setup.secret}</p>
            <div className="flex gap-2">
              <input className="input" placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
              <button className="btn-primary" onClick={enableTotp}>Enable</button>
            </div>
          </div>
        ) : (
          <button className="btn-primary" onClick={beginTotp}>Set up authenticator app</button>
        )}
      </div>

      <div className="card p-6 space-y-3">
        <h2 className="font-bold text-lg">Email one-time codes</h2>
        <p className="text-sm text-slate-500">Receive a login code by email as a second factor.</p>
        {me.email_otp_enabled ? (
          <div className="flex items-center justify-between">
            <span className="chip sev-low">Enabled</span>
            <button className="btn-ghost" onClick={() => toggleEmailOtp(false)}>Disable</button>
          </div>
        ) : (
          <button className="btn-primary" onClick={() => toggleEmailOtp(true)}>Enable email codes</button>
        )}
      </div>

      <form onSubmit={changePw} className="card p-6 space-y-3">
        <h2 className="font-bold text-lg">Change password</h2>
        <input className="input" type="password" placeholder="Current password" required
               value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
        <input className="input" type="password" placeholder="New password (min 10 chars)" required
               value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
        <button className="btn-primary">Update password</button>
      </form>
    </div>
  );
}
