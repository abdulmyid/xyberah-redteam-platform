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
  const frameworks = s.by_framework || {};
  const fwNames = Object.keys(frameworks);
  const fwData = (name) => Object.entries(frameworks[name] || {}).map(([k, v]) => ({ name: k, failed: v.failed, total: v.total }));
  const attacks = s.attack_methods || [];

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
          {(c.stages?.length ? c.stages : ["promptfoo", "custom", "garak", "pyrit", "inspect"].filter((t) => c.tools?.[t]).map((t) => ({ tool: t, status: "pending" }))).map((st, i) => {
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
          {s.analytics && (
            <div className="grid grid-cols-4 gap-3">
              <Stat label="Cost" value={`$${(s.analytics.total_cost || 0).toFixed(4)}`} />
              <Stat label="Tokens" value={s.analytics.total_tokens || 0} />
              <Stat label="Avg latency" value={`${s.analytics.avg_latency_ms || 0} ms`} />
              <Stat label="Requests" value={s.analytics.requests || 0} />
            </div>
          )}
          <div className="grid grid-cols-4 gap-2">
            {["critical","high","medium","low"].map((lvl) => (
              <div key={lvl} className={`rounded-lg p-3 text-center sev-${lvl}`}>
                <div className="text-2xl font-extrabold">{s.by_severity?.[lvl] || 0}</div>
                <div className="text-xs capitalize">{lvl}</div>
              </div>
            ))}
          </div>
          {fwNames.length > 0 && <FrameworkChart frameworks={frameworks} />}
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

      {/* Attack methods */}
      {attacks.length > 0 && (
        <div className="card p-5">
          <h2 className="font-bold mb-3">Attack methods</h2>
          <div className="space-y-2">
            {attacks.map((a) => (
              <div key={a.attack} className="flex items-center gap-3 text-sm">
                <div className="w-64 truncate font-mono text-xs" title={a.attack}>{a.attack}</div>
                <div className="flex-1 h-2 rounded-full bg-slate-200 overflow-hidden">
                  <div className="h-full" style={{ width: `${a.rate}%`, background: a.rate >= 50 ? "#dc2626" : a.rate > 0 ? "#d97706" : "#16a34a" }} />
                </div>
                <div className="w-28 text-right text-xs text-slate-600">{a.succeeded}/{a.total} ({a.rate}%)</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Drift / regression comparison */}
      {!running && findings.length > 0 && <DiffPanel campaignId={id} />}

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
        <FindingsTable findings={findings} campaignId={id} canRun={canRun} reload={reload} />
      </div>
    </div>
  );
}

const STATUS_LABELS = {
  open: "Open", triaged: "Triaged", fixed: "Fixed",
  accepted_risk: "Accepted risk", false_positive: "False positive",
};

function DiffPanel({ campaignId }) {
  const [options, setOptions] = useState([]);
  const [against, setAgainst] = useState("");
  const [diff, setDiff] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/api/campaigns").then((all) =>
      setOptions(all.filter((x) => String(x.id) !== String(campaignId) && x.status === "completed"))
    ).catch(() => {});
  }, [campaignId]);

  async function run(otherId) {
    if (!otherId) { setDiff(null); return; }
    setBusy(true);
    try { setDiff(await api.get(`/api/campaigns/${campaignId}/diff?against=${otherId}`)); }
    catch (e) { setDiff({ error: e.message }); }
    finally { setBusy(false); }
  }

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3 gap-3">
        <div>
          <h2 className="font-bold">Drift &amp; regression</h2>
          <p className="text-xs text-slate-500">Compare against a previous run to spot new vulnerabilities and fixes.</p>
        </div>
        <select className="input w-auto py-1 text-sm" value={against}
                onChange={(e) => { setAgainst(e.target.value); run(e.target.value); }}>
          <option value="">Compare to…</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name} · risk {o.summary?.risk_score ?? "?"}{o.finished_at ? ` · ${new Date(o.finished_at).toLocaleDateString()}` : ""}
            </option>
          ))}
        </select>
      </div>
      {busy && <p className="text-sm text-slate-500">Comparing…</p>}
      {diff?.error && <p className="text-sm text-red-600">{diff.error}</p>}
      {diff && !diff.error && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            <Stat label="New" value={diff.counts.new} tone="text-red-600" />
            <Stat label="Fixed" value={diff.counts.fixed} tone="text-green-600" />
            <Stat label="Still failing" value={diff.counts.persisting} />
            <Stat label="Risk Δ" value={`${diff.risk_delta > 0 ? "+" : ""}${diff.risk_delta}`}
                  tone={diff.risk_delta > 0 ? "text-red-600" : diff.risk_delta < 0 ? "text-green-600" : ""} />
          </div>
          <div className="text-xs text-slate-500">
            Baseline: <b>{diff.baseline.name}</b> (risk {diff.baseline.risk_score}, {diff.baseline.failed} failing)
            {" → "}current: <b>{diff.current.name}</b> (risk {diff.current.risk_score}, {diff.current.failed} failing)
          </div>
          {diff.new.length > 0 && (
            <DiffList title="New vulnerabilities (regressions)" tone="sev-high" rows={diff.new} />
          )}
          {diff.fixed.length > 0 && (
            <DiffList title="Fixed since baseline" tone="sev-low" rows={diff.fixed} />
          )}
        </div>
      )}
    </div>
  );
}

function DiffList({ title, tone, rows }) {
  return (
    <div>
      <div className="text-sm font-semibold mb-2">{title} ({rows.length})</div>
      <div className="space-y-1">
        {rows.slice(0, 50).map((r) => (
          <div key={`${r.id}-${r.plugin}`} className="flex items-center gap-2 text-xs">
            <span className={`chip ${tone}`}>{r.severity}</span>
            <span className="font-mono">{r.plugin}</span>
            <span className="text-slate-500 truncate" title={r.prompt}>{r.prompt?.slice(0, 120)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function FrameworkChart({ frameworks }) {
  const names = Object.keys(frameworks);
  const [sel, setSel] = useState(names[0]);
  const data = Object.entries(frameworks[sel] || {}).map(([k, v]) => ({ name: k, failed: v.failed, total: v.total }));
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold">Framework compliance</div>
        <select className="input w-auto py-1 text-xs" value={sel} onChange={(e) => setSel(e.target.value)}>
          {names.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      <ResponsiveContainer width="100%" height={210}>
        <BarChart data={data} layout="vertical" margin={{ left: 20 }}>
          <XAxis type="number" hide /><YAxis type="category" dataKey="name" width={180} tick={{ fontSize: 10 }} />
          <Tooltip />
          <Bar dataKey="failed" radius={4}>{data.map((_, i) => <Cell key={i} fill="var(--brand-primary)" />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function FindingsTable({ findings, campaignId, canRun, reload }) {
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
              <tr><th className="p-2 w-6"></th><th className="p-2">Sev</th><th className="p-2">Tool</th><th className="p-2">Category</th><th className="p-2">Test</th><th className="p-2">Status</th><th className="p-2">Prompt</th></tr>
            </thead>
            <tbody>
              {rows.slice(0, 200).map((f) => (
                <FindingRow key={f.id} f={f} campaignId={campaignId} canRun={canRun} reload={reload} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FindingRow({ f, campaignId, canRun, reload }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(f.triage_note || "");

  const patch = async (body) => {
    setBusy(true);
    try { await api.patch(`/api/campaigns/${campaignId}/findings/${f.id}`, body); reload(); }
    catch (e) { alert(e.message); } finally { setBusy(false); }
  };
  const retest = async () => {
    setBusy(true);
    try { await api.post(`/api/campaigns/${campaignId}/findings/${f.id}/retest`); reload(); }
    catch (e) { alert(e.message); } finally { setBusy(false); }
  };

  const statusTone = { fixed: "sev-low", false_positive: "bg-slate-200", accepted_risk: "sev-medium",
    triaged: "bg-slate-100", open: "bg-slate-100" }[f.status || "open"];

  return (
    <>
      <tr className="border-t hover:bg-slate-50 cursor-pointer" onClick={() => setOpen((o) => !o)}>
        <td className="p-2 text-slate-400">{open ? "▾" : "▸"}</td>
        <td className="p-2"><Severity level={f.severity} /></td>
        <td className="p-2">{f.tool}</td>
        <td className="p-2">{f.category}</td>
        <td className="p-2 font-mono">{f.plugin}</td>
        <td className="p-2"><span className={`chip ${statusTone}`}>{STATUS_LABELS[f.status || "open"]}</span></td>
        <td className="p-2 max-w-xs truncate" title={f.prompt}>{f.prompt?.slice(0, 120)}</td>
      </tr>
      {open && (
        <tr className="border-t bg-slate-50">
          <td></td>
          <td colSpan={6} className="p-3 space-y-3">
            {f.prompt && (
              <div><div className="text-slate-500 font-semibold mb-1">Prompt</div>
                <pre className="bg-white border rounded p-2 whitespace-pre-wrap max-h-40 overflow-auto">{f.prompt}</pre></div>
            )}
            {f.output && (
              <div><div className="text-slate-500 font-semibold mb-1">Response</div>
                <pre className="bg-white border rounded p-2 whitespace-pre-wrap max-h-40 overflow-auto">{f.output}</pre></div>
            )}
            {f.reason && (
              <div><div className="text-slate-500 font-semibold mb-1">Why it failed</div>
                <div className="bg-white border rounded p-2">{f.reason}</div></div>
            )}
            {f.retested_at && (
              <div className={`rounded p-2 ${f.retest_passed === true ? "sev-low" : f.retest_passed === false ? "sev-high" : "bg-white border"}`}>
                <div className="font-semibold">
                  Retest · {new Date(f.retested_at).toLocaleString()} ·{" "}
                  {f.retest_passed === true ? "now passes ✓" : f.retest_passed === false ? "still fails ✗" : "response captured (review manually)"}
                </div>
                {f.retest_output && <pre className="mt-1 whitespace-pre-wrap max-h-32 overflow-auto">{f.retest_output}</pre>}
              </div>
            )}
            {canRun && (
              <div className="flex flex-wrap items-end gap-3 pt-2 border-t">
                <div>
                  <div className="text-slate-500 mb-1">Status</div>
                  <select className="input w-auto py-1" value={f.status || "open"} disabled={busy}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => patch({ status: e.target.value })}>
                    {Object.entries(STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="flex-1 min-w-[200px]">
                  <div className="text-slate-500 mb-1">Triage note</div>
                  <div className="flex gap-2">
                    <input className="input py-1 flex-1" value={note} onClick={(e) => e.stopPropagation()}
                           onChange={(e) => setNote(e.target.value)} placeholder="Add a note…" />
                    <button className="btn-ghost py-1" disabled={busy} onClick={(e) => { e.stopPropagation(); patch({ triage_note: note }); }}>Save</button>
                  </div>
                </div>
                <button className="btn-primary py-1" disabled={busy} onClick={(e) => { e.stopPropagation(); retest(); }}>
                  {busy ? "Working…" : "Retest"}
                </button>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
