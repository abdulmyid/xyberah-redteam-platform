import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function Tls() {
  const [st, setSt] = useState(null);
  const [cert, setCert] = useState(null);
  const [key, setKey] = useState(null);
  const [msg, setMsg] = useState("");

  const load = () => api.get("/api/tls").then(setSt);
  useEffect(() => { load(); }, []);

  async function upload(e) {
    e.preventDefault(); setMsg("");
    if (!cert || !key) return setMsg("Choose both a certificate and a private key.");
    const fd = new FormData(); fd.append("cert", cert); fd.append("key", key);
    try { await api.upload("/api/tls", fd); setMsg("Certificate installed. The proxy reloads within a few seconds."); load(); }
    catch (e) { setMsg(e.message); }
  }
  async function reset() {
    setMsg("");
    await api.del("/api/tls"); setMsg("Reverted to the automatic self-signed certificate."); load();
  }

  if (!st) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="card p-6 space-y-4 max-w-xl">
      <h2 className="font-bold text-lg">Frontend TLS certificate</h2>
      <p className="text-sm text-slate-500">
        The app is served over HTTPS. By default it uses an automatically generated self-signed
        certificate. Upload your company certificate to replace it.
      </p>

      <div className="rounded-lg border p-3 text-sm">
        {st.mode === "custom" ? (
          <div className="space-y-1">
            <div><span className="chip sev-low">Custom certificate active</span></div>
            <div className="text-slate-600">Subject: {st.subject}</div>
            {st.sans?.length > 0 && <div className="text-slate-600">SANs: {st.sans.join(", ")}</div>}
            <div className="text-slate-600">Expires: {st.not_after}{st.expired && <span className="text-red-600"> (expired)</span>}</div>
          </div>
        ) : (
          <div><span className="chip sev-medium">Self-signed (automatic)</span>
            <span className="text-slate-500 ml-2">Browsers will warn until you upload a trusted certificate.</span></div>
        )}
      </div>

      {msg && <div className="rounded bg-slate-100 text-sm px-3 py-2">{msg}</div>}

      <form onSubmit={upload} className="space-y-3">
        <div><label className="label">Certificate (PEM, full chain)</label>
          <input type="file" accept=".crt,.pem,.cer" onChange={(e) => setCert(e.target.files[0])} /></div>
        <div><label className="label">Private key (PEM, unencrypted)</label>
          <input type="file" accept=".key,.pem" onChange={(e) => setKey(e.target.files[0])} /></div>
        <div className="flex gap-2">
          <button className="btn-primary">Install certificate</button>
          {st.mode === "custom" && <button type="button" className="btn-ghost" onClick={reset}>Revert to self-signed</button>}
        </div>
      </form>
    </div>
  );
}
