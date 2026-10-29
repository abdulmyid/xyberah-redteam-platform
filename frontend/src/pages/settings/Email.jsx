import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function Email() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({ host: "", port: 587, username: "", password: "", from_addr: "", from_name: "Xyberah", use_tls: true });
  const [msg, setMsg] = useState("");
  const [test, setTest] = useState("");

  useEffect(() => {
    api.get("/api/smtp").then((c) => { setCfg(c); setForm((f) => ({ ...f, ...c, password: "" })); });
  }, []);

  async function save(e) {
    e.preventDefault(); setMsg("");
    try { const c = await api.put("/api/smtp", form); setCfg(c); setMsg("Saved."); }
    catch (e) { setMsg(e.message); }
  }
  async function sendTest() {
    setMsg("");
    try { const r = await api.post(`/api/smtp/test?to=${encodeURIComponent(test)}`); setMsg(`Test sent via ${r.delivered}.`); }
    catch (e) { setMsg(e.message); }
  }

  if (!cfg) return <p className="text-slate-500">Loading…</p>;

  return (
    <form onSubmit={save} className="card p-6 space-y-4 max-w-xl">
      <h2 className="font-bold text-lg">Outbound email (SMTP)</h2>
      <p className="text-sm text-slate-500">
        Used for invites and email login codes. {cfg.configured ? "Currently configured." : "Not set — emails are written to the server's outbox folder for testing."}
      </p>
      {msg && <div className="rounded bg-slate-100 text-sm px-3 py-2">{msg}</div>}
      <div className="grid sm:grid-cols-2 gap-4">
        <div><label className="label">Host</label><input className="input" value={form.host || ""} onChange={(e) => setForm({ ...form, host: e.target.value })} /></div>
        <div><label className="label">Port</label><input className="input" type="number" value={form.port || 587} onChange={(e) => setForm({ ...form, port: +e.target.value })} /></div>
        <div><label className="label">Username</label><input className="input" value={form.username || ""} onChange={(e) => setForm({ ...form, username: e.target.value })} /></div>
        <div><label className="label">Password</label><input className="input" type="password" placeholder={cfg.configured ? "(unchanged)" : ""} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
        <div><label className="label">From address</label><input className="input" value={form.from_addr || ""} onChange={(e) => setForm({ ...form, from_addr: e.target.value })} /></div>
        <div><label className="label">From name</label><input className="input" value={form.from_name || ""} onChange={(e) => setForm({ ...form, from_name: e.target.value })} /></div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.use_tls} onChange={(e) => setForm({ ...form, use_tls: e.target.checked })} /> Use STARTTLS (port 587)
      </label>
      <div className="flex items-center gap-2">
        <button className="btn-primary">Save SMTP</button>
      </div>
      <div className="border-t pt-4 flex items-end gap-2">
        <div className="flex-1"><label className="label">Send a test email to</label>
          <input className="input" value={test} onChange={(e) => setTest(e.target.value)} placeholder="you@company.com" /></div>
        <button type="button" className="btn-ghost" onClick={sendTest} disabled={!test}>Send test</button>
      </div>
    </form>
  );
}
