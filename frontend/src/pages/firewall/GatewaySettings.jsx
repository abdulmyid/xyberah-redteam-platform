import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function GatewaySettings() {
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState("");
  const [verify, setVerify] = useState(null);

  useEffect(() => { api.get("/api/gateway/settings").then(setS).catch((e) => setMsg(e.message)); }, []);

  async function save() {
    setMsg("");
    try { setS(await api.put("/api/gateway/settings", s)); setMsg("Saved ✓ — the gateway picks this up within 30 seconds."); }
    catch (e) { setMsg(e.message); }
  }
  async function runVerify() {
    setVerify({ running: true });
    try { setVerify(await api.get("/api/gateway/audit/verify")); } catch (e) { setVerify({ error: e.message }); }
  }

  if (!s) return <p className="text-slate-500">{msg || "Loading…"}</p>;
  const num = (k) => (e) => setS({ ...s, [k]: +e.target.value });

  return (
    <div className="max-w-2xl space-y-5">
      <div className="card p-5 space-y-3">
        <div className="font-semibold">Gateway</div>
        <div><label className="label">Public base URL (shown to users in quick-start snippets)</label>
          <input className="input" value={s.public_base_url} onChange={(e) => setS({ ...s, public_base_url: e.target.value })} placeholder="https://ai.example.com:8080" /></div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label">Max request body (KB)</label>
            <input type="number" min="16" className="input" value={s.max_body_kb} onChange={num("max_body_kb")} /></div>
          <div><label className="label">Stream look-behind window (chars)</label>
            <input type="number" min="16" max="4096" className="input" value={s.stream_holdback} onChange={num("stream_holdback")} />
            <p className="text-xs text-slate-500 mt-1">Larger windows catch longer secrets split across chunks, at the cost of slightly later token delivery.</p></div>
        </div>
      </div>
      <div className="card p-5 space-y-3">
        <div className="font-semibold">Audit trail &amp; retention</div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label">Traffic log retention in the UI (days)</label>
            <input type="number" min="1" className="input" value={s.event_retention_days} onChange={num("event_retention_days")} /></div>
          <div><label className="label">Hash-chained audit file retention (days, 0 = forever)</label>
            <input type="number" min="0" className="input" value={s.file_retention_days} onChange={num("file_retention_days")} /></div>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.log_to_stdout} onChange={(e) => setS({ ...s, log_to_stdout: e.target.checked })} /> Also write each audit record as a JSON line to the container log</label>
        <p className="text-xs text-slate-500">Records are also forwarded as CEF to the syslog target configured under Settings → Operations &amp; health.</p>
        <div className="flex items-center gap-3">
          <button className="btn-ghost" onClick={runVerify}>Verify audit chain</button>
          {verify?.running && <span className="text-sm text-slate-500">Verifying…</span>}
          {verify && !verify.running && !verify.error && (
            <span className={`text-sm ${verify.valid ? "text-green-700" : "text-red-700"}`}>
              {verify.valid ? `✓ Intact — ${verify.records} records in ${verify.files} files` :
                `✗ Broken: ${Object.values(verify.hosts).filter((h) => !h.valid).map((h) => `${h.broken.file} line ${h.broken.line} (${h.broken.reason})`).join("; ")}`}
            </span>
          )}
          {verify?.error && <span className="text-sm text-red-700">{verify.error}</span>}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button className="btn-primary" onClick={save}>Save settings</button>
        {msg && <span className="text-sm text-slate-600">{msg}</span>}
      </div>
    </div>
  );
}
