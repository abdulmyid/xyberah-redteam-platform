import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const mb = (n) => (n == null ? "—" : n < 1024 * 1024 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

export default function Operations() {
  const [h, setH] = useState(null);
  const [msg, setMsg] = useState("");
  const [clean, setClean] = useState({ events_days: 30, clear_outbox: false, vacuum: true });
  const [rotateDays, setRotateDays] = useState(90);
  const [sys, setSys] = useState({ enabled: false, host: "", port: 514, protocol: "udp" });

  const loadHealth = () => api.get("/api/ops/health").then(setH).catch((e) => setMsg(e.message));
  useEffect(() => {
    loadHealth();
    api.get("/api/ops/syslog").then(setSys).catch(() => {});
  }, []);

  async function runCleanup() {
    setMsg("Cleaning…");
    try { const r = await api.post("/api/ops/cleanup", clean);
      setMsg(`Removed ${r.events_removed} event logs, ${r.outbox_removed} outbox files${r.vacuumed ? ", DB vacuumed" : ""}.`);
      loadHealth();
    } catch (e) { setMsg(e.message); }
  }
  async function rotateAudit() {
    if (!confirm(`Archive audit entries older than ${rotateDays} days and re-anchor the chain?`)) return;
    setMsg("Rotating…");
    try { const r = await api.post("/api/ops/audit/rotate", { before_days: rotateDays });
      setMsg(`Archived ${r.archived} entries${r.file ? ` to ${r.file}` : ""}; ${r.remaining} remain.`);
      loadHealth();
    } catch (e) { setMsg(e.message); }
  }
  async function saveSyslog() {
    try { setSys(await api.put("/api/ops/syslog", sys)); setMsg("Syslog settings saved ✓"); loadHealth(); }
    catch (e) { setMsg(e.message); }
  }
  async function testSyslog() {
    setMsg("Sending test…");
    const r = await api.post("/api/ops/syslog/test", sys);
    setMsg(r.ok ? "Test datagram sent ✓" : `Test failed: ${r.error || ""}`);
  }

  const Stat = ({ label, value }) => (
    <div className="rounded-lg border border-slate-200 p-3"><div className="text-lg font-bold">{value}</div><div className="text-xs text-slate-500">{label}</div></div>
  );

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <h2 className="font-bold text-lg">Operations &amp; health</h2>
        <p className="text-sm text-slate-500">System metrics, storage cleanup, audit-log rotation, and syslog forwarding.</p>
      </div>

      {!h ? <p className="text-slate-500">Loading…</p> : (
        <>
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
            <Stat label="Companies" value={h.counts.companies} />
            <Stat label="Users" value={h.counts.users} />
            <Stat label="Campaigns" value={h.counts.campaigns} />
            <Stat label="Running" value={h.running} />
            <Stat label="Findings" value={h.counts.findings} />
            <Stat label="Audit rows" value={h.counts.audit_rows} />
            <Stat label="Prompt sets" value={h.counts.prompt_sets} />
            <Stat label="Schedules" value={h.counts.schedules} />
          </div>
          <div className="card p-4 text-sm grid sm:grid-cols-2 gap-2">
            <div>DB size: <b>{mb(h.storage.db_bytes)}</b></div>
            <div>Campaign data: <b>{mb(h.storage.campaigns_bytes)}</b></div>
            <div>Uploads: <b>{mb(h.storage.uploads_bytes)}</b></div>
            <div>Dev outbox: <b>{mb(h.storage.outbox_bytes)}</b></div>
            {h.disk.total && <div className="sm:col-span-2 text-slate-600">Disk: {mb(h.disk.used)} / {mb(h.disk.total)} used ({h.disk.percent_used}%)</div>}
          </div>
          <div className="card p-4 text-sm">
            <div className="font-semibold mb-1">Scanner engines</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(h.tools).map(([k, v]) => (
                <span key={k} className={`chip ${v.ready ? "sev-low" : "bg-slate-200"}`}>{k} {v.installed || "—"}</span>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="card p-5 space-y-3">
        <div className="font-semibold text-sm">Cleanup</div>
        <div className="flex flex-wrap items-end gap-3">
          <div><label className="label">Delete live-event logs older than (days)</label>
            <input type="number" min="0" className="input w-32" value={clean.events_days}
                   onChange={(e) => setClean({ ...clean, events_days: +e.target.value })} /></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={clean.clear_outbox}
            onChange={(e) => setClean({ ...clean, clear_outbox: e.target.checked })} /> Clear dev outbox</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={clean.vacuum}
            onChange={(e) => setClean({ ...clean, vacuum: e.target.checked })} /> VACUUM database</label>
          <button className="btn-ghost" onClick={runCleanup}>Run cleanup</button>
        </div>
        <p className="text-xs text-slate-500">Event logs are the live scan logs; findings and reports are kept.</p>
      </div>

      <div className="card p-5 space-y-3">
        <div className="font-semibold text-sm">Audit-log rotation</div>
        <div className="flex flex-wrap items-end gap-3">
          <div><label className="label">Archive entries older than (days)</label>
            <input type="number" min="1" className="input w-32" value={rotateDays}
                   onChange={(e) => setRotateDays(+e.target.value)} /></div>
          <button className="btn-ghost" onClick={rotateAudit}>Rotate audit log</button>
        </div>
        <p className="text-xs text-slate-500">Old entries are archived to a JSONL file in the data volume; the remaining chain is re-anchored so integrity verification still passes.</p>
      </div>

      <div className="card p-5 space-y-3">
        <div className="font-semibold text-sm">Syslog forwarding (audit events)</div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label">Host</label>
            <input className="input" value={sys.host} onChange={(e) => setSys({ ...sys, host: e.target.value })} placeholder="siem.acme.com" /></div>
          <div className="flex gap-2">
            <div><label className="label">Port</label>
              <input type="number" className="input w-28" value={sys.port} onChange={(e) => setSys({ ...sys, port: +e.target.value })} /></div>
            <div><label className="label">Protocol</label>
              <select className="input w-auto" value={sys.protocol} onChange={(e) => setSys({ ...sys, protocol: e.target.value })}>
                <option value="udp">UDP</option><option value="tcp">TCP</option>
              </select></div>
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={sys.enabled}
          onChange={(e) => setSys({ ...sys, enabled: e.target.checked })} /> Forward audit events to syslog (CEF)</label>
        <div className="flex items-center gap-3">
          <button className="btn-primary" onClick={saveSyslog}>Save</button>
          <button className="btn-ghost" onClick={testSyslog}>Send test</button>
        </div>
      </div>

      {msg && <div className="text-sm text-slate-600">{msg}</div>}
    </div>
  );
}
