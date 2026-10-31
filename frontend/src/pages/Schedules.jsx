import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, atLeast } from "../lib/api";
import { useApp } from "../lib/context.jsx";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function freqText(f) {
  if (!f) return "—";
  if (f.kind === "interval") return `Every ${Math.round((f.minutes || 1440) / 60)}h`;
  if (f.kind === "weekly") return `Weekly · ${DAYS[f.day || 0]} ${f.at || "02:00"} UTC`;
  return `Daily · ${f.at || "02:00"} UTC`;
}
const fmt = (d) => (d ? new Date(d).toLocaleString() : "—");

export default function Schedules() {
  const nav = useNavigate();
  const { user } = useApp();
  const canEdit = atLeast(user.role, "analyst");
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState("");

  const load = () => api.get("/api/schedules").then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  async function toggle(s) {
    setBusy(s.id);
    try {
      const full = await api.get(`/api/schedules/${s.id}`);
      await api.put(`/api/schedules/${s.id}`, {
        name: full.campaign_name || full.name, template: full.template,
        freq: full.freq, enabled: !s.enabled,
      });
      load();
    } catch (e) { alert(e.message); } finally { setBusy(""); }
  }
  async function runNow(s) {
    setBusy(s.id);
    try { const r = await api.post(`/api/schedules/${s.id}/run-now`); nav(`/campaigns/${r.campaign_id}`); }
    catch (e) { alert(e.message); setBusy(""); }
  }
  async function remove(s) {
    if (!confirm(`Delete schedule "${s.name}"?`)) return;
    await api.del(`/api/schedules/${s.id}`); load();
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-extrabold">Schedules</h1>
          <p className="text-sm text-slate-500 mt-1">Recurring scans that run automatically so you catch model drift and regressions.</p>
        </div>
        {canEdit && <button className="btn-primary" onClick={() => nav("/campaigns/new")}>+ New scheduled scan</button>}
      </div>

      {rows === null ? <p className="text-slate-500">Loading…</p>
        : rows.length === 0 ? (
          <div className="card p-8 text-center text-slate-500">
            No schedules yet. Create a campaign and turn on “Run on a schedule”.
          </div>
        ) : (
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Name</th><th className="px-4 py-2">Target</th>
                  <th className="px-4 py-2">Frequency</th><th className="px-4 py-2">Next run</th>
                  <th className="px-4 py-2">Last run</th><th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="border-t border-slate-100">
                    <td className="px-4 py-3">
                      <div className="font-medium">{s.name}</div>
                      <span className={`chip ${s.enabled ? "sev-low" : "bg-slate-200"}`}>{s.enabled ? "enabled" : "paused"}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{s.target_type || "—"}</td>
                    <td className="px-4 py-3 text-slate-600">{freqText(s.freq)}</td>
                    <td className="px-4 py-3 text-slate-600">{s.enabled ? fmt(s.next_run_at) : "—"}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {s.last_campaign_id
                        ? <a className="underline" href={`/campaigns/${s.last_campaign_id}`}>{fmt(s.last_run_at)}</a>
                        : fmt(s.last_run_at)}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {canEdit && (
                        <>
                          <button className="btn-ghost py-1 text-sm" disabled={busy === s.id} onClick={() => runNow(s)}>Run now</button>
                          <button className="btn-ghost py-1 text-sm" disabled={busy === s.id} onClick={() => toggle(s)}>{s.enabled ? "Pause" : "Resume"}</button>
                          <button className="btn-ghost py-1 text-sm text-red-500" onClick={() => remove(s)}>Delete</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </div>
  );
}
