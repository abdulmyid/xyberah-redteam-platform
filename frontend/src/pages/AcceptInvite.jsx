import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api";

export default function AcceptInvite() {
  const { token } = useParams();
  const nav = useNavigate();
  const [info, setInfo] = useState(null);
  const [form, setForm] = useState({ username: "", password: "", confirm: "" });
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.get(`/api/auth/invite/${token}`).then(setInfo).catch((e) => setErr(e.message));
  }, [token]);

  async function submit(e) {
    e.preventDefault();
    setErr("");
    if (form.password !== form.confirm) return setErr("Passwords do not match");
    try {
      await api.post("/api/auth/invite/accept", { token, username: form.username, password: form.password });
      setDone(true);
      setTimeout(() => nav("/login"), 1500);
    } catch (e) { setErr(e.message); }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="card w-full max-w-md p-8">
        <h1 className="text-xl font-extrabold mb-1">Accept your invitation</h1>
        {err && <div className="my-3 rounded-lg bg-red-50 text-red-700 text-sm px-3 py-2">{err}</div>}
        {done ? (
          <p className="text-green-700 text-sm">Account created. Redirecting to sign in…</p>
        ) : info ? (
          <form onSubmit={submit} className="space-y-4 mt-4">
            <p className="text-sm text-slate-600">Setting up <b>{info.email}</b>.</p>
            <div><label className="label">Display name</label>
              <input className="input" value={form.username} required
                     onChange={(e) => setForm({ ...form, username: e.target.value })} /></div>
            <div><label className="label">Password (min 10 chars)</label>
              <input className="input" type="password" value={form.password} required
                     onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
            <div><label className="label">Confirm password</label>
              <input className="input" type="password" value={form.confirm} required
                     onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></div>
            <button className="btn-primary w-full">Create account</button>
          </form>
        ) : !err ? (
          <p className="text-slate-500 text-sm">Checking invitation…</p>
        ) : (
          <Link to="/login" className="text-sm" style={{ color: "var(--brand-primary)" }}>Go to sign in</Link>
        )}
      </div>
    </div>
  );
}
