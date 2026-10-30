import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { api, atLeast } from "../lib/api";
import { useApp } from "../lib/context.jsx";
import { Status, RiskGauge, Severity, Stat } from "../components/ui.jsx";

const SEV_COLOR = { critical: "#b91c1c", high: "#ea580c", medium: "#d97706", low: "#16a34a" };

export default function CampaignDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user } = useApp();
  const [c, setC] = useState(null);
  const [findings, setFindings] = useState([]);
  const [logs, setLogs] = useState([]);
  const [progress, setProgress] = useState({});
  const logRef = useRef(null);

  const reload = useCallback(() => {
    api.get(`/api/campaigns/${id}`).then(setC);
    api.get(`/api/campaigns/${id}/findings`).then(setFindings);
  }, [id]);

  useEffect(() => { reload(); }, [reload]);

  // Live event stream
  useEffect(() => {
    const es = new EventSource(`/api/campaigns/${id}/events`, { withCredentials: true });
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.kind === "log") setLogs((l) => [...l.slice(-400), ev]);
      else if (ev.kind === "progress") setProgress((p) => ({ ...p, [ev.tool]: { done: ev.done, total: ev.total } }));
      else if (ev.kind === "stage" || ev.kind === "status") reload();
      if (ev.kind === "status" && ev.final) { reload(); es.close(); }
    };
    es.onerror = () => {}; // auto-reconnect
    return () => es.close();
  }, [id, reload]);

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [logs]);

  const act = async (verb) => { await api.post(`/api/campaigns/${id}/${verb}`).catch((e) => alert(e.message)); reload(); };
  const remove = async () => {
    if (!confirm("Delete this campaign and all its findings? This cannot be undone.")) return;
    try { await api.del(`/api/campaigns/${id}`); nav("/"); }
    catch (e) { alert(e.message); }
  };
  const share = async () => {
    const r = await api.post(`/api/campaigns/${id}/share`);
    navigator.clipboard?.writeText(`${location.origin}${r.url}.html`);
    alert("Shareable report link copied to clipboard.");
  };

  if (!c) return <p className="text-slate-500">Loading…</p>;
  const s = c.summary || {};
  const running = ["running", "queued", "stopping"].includes(c.status);
  const canRun = atLeast(user.role, "analyst");
  const catData = Object.entries(s.by_category || {}).map(([k, v]) => ({ name: k, failed: v.failed, total: v.total }));

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold">{c.name}</h1><Status value={c.status} />
          </div>
          <p className="text-sm text-slate-500">{c.target_display}</p>
        </div>
        {canRun && (
          <div className="flex gap-2">
            {c.status === "draft" || c.status === "completed" || c.status === "stopped" || c.status === "failed" ? (
              <button className="btn-primary" onClick={() => act("start")}>Start</button>
            ) : null}
            {c.status === "running" && <button className="btn-ghost" onClick={() => act("pause")}>Pause</button>}
            {c.status === "paused" && <button className="btn-primary" onClick={() => act("resume")}>Resume</button>}
            {running && <button className="btn-danger" onClick={() => act("stop")}>Stop</button>}
            {!running && <button className="btn-ghost" onClick={remove}>Delete</button>}
          </div>
        )}
      </div>

      {/* Stages / progress */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold">Stages</h2>
          {c.status === "paused" && <span className="text-xs text-amber-600">Paused between stages — Resume to continue</span>}
        </div>
        <div className="grid sm:grid-cols-4 gap-3">
          {(c.stages?.length ? c.stages : ["promptfoo", "garak", "pyrit", "inspect"].filter((t) => c.tools?.[t]).map((t) => ({ tool: t, status: "pending" }))).map((st, i) => {
            const p = progress[st.tool];
            return (
              <div key={i} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-semibold">{st.tool}</span><Status value={st.status} />
                </div>
                {p && st.status === "running" && (
                  <div className="mt-2">
                    <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
                      <div className="h-full" style={{ width: `${(100 * p.done) / Math.max(p.total, 1)}%`, background: "var(--brand-primary)" }} />
                    </div>
                    <div className="text-xs text-slate-500 mt-1">{p.done}/{p.total}</div>
                  </div>
                )}
                {st.status === "done" && <div className="text-xs text-slate-500 mt-1">{st.done ?? 0} findings</div>}
                {st.error && <div className="text-xs text-red-600 mt-1 truncate">{st.error}</div>}
              </div>
            );
          })}
        </div>
      </div>

      {/* Summary */}
      <div className="grid md:grid-cols-[auto,1fr] gap-5">
        <div className="card p-5 flex flex-col items-center justify-center">
          <RiskGauge score={s.risk_score || 0} band={s.risk_band || "low"} />
          <span className={`chip sev-${s.risk_band || "low"} mt-2`}>{s.risk_band || "low"} risk</span>
        </div>
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            <Stat label="Tests" value={s.total || 0} />
            <Stat label="Failed" value={s.failed || 0} tone="text-red-600" />
            <Stat label="Pass rate" value={`${s.pass_rate ?? 100}%`} />
            <Stat label="Critical+High" value={(s.by_severity?.critical || 0) + (s.by_severity?.high || 0)} />
          </div>
          {catData.length > 0 && (
            <div className="card p-4">
              <div className="text-sm font-semibold mb-2">Failures by category</div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={catData} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" hide /><YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="failed" radius={4}>
                    {catData.map((_, i) => <Cell key={i} fill="var(--brand-primary)" />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* Live log */}
      {(running || logs.length > 0) && (
        <div className="card p-0 overflow-hidden">
          <div className="px-4 py-2 border-b text-sm font-semibold bg-slate-50">Live log</div>
          <div ref={logRef} className="h-56 overflow-auto bg-slate-900 text-slate-100 text-xs font-mono p-3 space-y-0.5">
            {logs.map((l, i) => (
              <div key={i}><span className="text-slate-500">[{l.tool}]</span> {l.line}</div>
            ))}
          </div>
        </div>
      )}

      {/* Reports */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold">Reports</h2>
          <div className="flex gap-2">
            <a className="btn-ghost" href={`/api/campaigns/${id}/report.html`} target="_blank" rel="noreferrer">HTML</a>
            <a className="btn-ghost" href={`/api/campaigns/${id}/report.pdf`}>PDF</a>
            <a className="btn-ghost" href={`/api/campaigns/${id}/report.json`}>JSON</a>
            <a className="btn-ghost" href={`/api/campaigns/${id}/report.csv`}>CSV</a>
            <button className="btn-ghost" onClick={share}>Share link</button>
          </div>
        </div>
        <FindingsTable findings={findings} />
      </div>
    </div>
  );
}

function FindingsTable({ findings }) {
  const [tab, setTab] = useState("failed");
  const rows = findings.filter((f) => (tab === "failed" ? !f.passed : true))
    .sort((a, b) => ["critical", "high", "medium", "low"].indexOf(a.severity) - ["critical", "high", "medium", "low"].indexOf(b.severity));
  return (
    <div>
      <div className="flex gap-2 mb-3">
        <button className={`tab ${tab === "failed" ? "tab-active" : ""}`} onClick={() => setTab("failed")}>Failures ({findings.filter((f) => !f.passed).length})</button>
        <button className={`tab ${tab === "all" ? "tab-active" : ""}`} onClick={() => setTab("all")}>All ({findings.length})</button>
      </div>
      {rows.length === 0 ? <p className="text-sm text-slate-500">No findings yet.</p> : (
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-slate-500 text-left">
              <tr><th className="p-2">Sev</th><th className="p-2">Tool</th><th className="p-2">Category</th><th className="p-2">Test</th><th className="p-2">Prompt</th></tr>
            </thead>
            <tbody>
              {rows.slice(0, 200).map((f) => (
                <tr key={f.id} className="border-t">
                  <td className="p-2"><Severity level={f.severity} /></td>
                  <td className="p-2">{f.tool}</td>
                  <td className="p-2">{f.category}</td>
                  <td className="p-2 font-mono">{f.plugin}</td>
                  <td className="p-2 max-w-md truncate" title={f.prompt}>{f.prompt?.slice(0, 160)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
