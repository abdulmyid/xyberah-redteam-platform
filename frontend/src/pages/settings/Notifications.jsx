import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useApp } from "../../lib/context.jsx";

const KINDS = [
  { id: "slack", label: "Slack (incoming webhook)" },
  { id: "teams", label: "Microsoft Teams (webhook)" },
  { id: "webhook", label: "Generic webhook (JSON POST)" },
];
const empty = { name: "", kind: "slack", url: "", min_risk: 0, on_complete: true, enabled: true };

export default function Notifications() {
  const { user } = useApp();
  const isGlobal = user.role === "global_admin";
  const [channels, setChannels] = useState(null);
  const [draft, setDraft] = useState(empty);
  const [msg, setMsg] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  const load = () => api.get("/api/notify/channels").then(setChannels).catch(() => setChannels([]));
  useEffect(() => { load(); api.get("/api/notify/base-url").then((r) => setBaseUrl(r.url || "")).catch(() => {}); }, []);

  async function add() {
    if (!draft.url) return setMsg("Enter the webhook URL.");
    setMsg("");
    try { await api.post("/api/notify/channels", draft); setDraft(empty); load(); }
    catch (e) { setMsg(e.message); }
  }
  async function test() {
    if (!draft.url) return setMsg("Enter a URL to test.");
    setMsg("Sending test…");
    const r = await api.post("/api/notify/test", { kind: draft.kind, url: draft.url });
    setMsg(r.ok ? "Test sent ✓ — check the channel." : `Test failed: ${r.error || ""}`);
  }
  async function toggle(c) { await api.put(`/api/notify/channels/${c.id}`, { ...c, url: "", enabled: !c.enabled }); load(); }
  async function remove(c) { if (confirm(`Delete channel "${c.name}"?`)) { await api.del(`/api/notify/channels/${c.id}`); load(); } }
  async function saveBase() { await api.put("/api/notify/base-url", { url: baseUrl }); setMsg("Base URL saved ✓"); }

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h2 className="font-bold text-lg">Alerts &amp; notifications</h2>
        <p className="text-sm text-slate-500">Get a message when a scan finishes (optionally only above a risk score).</p>
      </div>

      {channels === null ? <p className="text-slate-500">Loading…</p> : channels.length > 0 && (
        <div className="space-y-2">
          {channels.map((c) => (
            <div key={c.id} className="card p-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="font-semibold">{c.name} <span className="text-xs text-slate-400">({c.kind})</span></div>
                <div className="text-xs text-slate-500 truncate">{c.url_preview}</div>
                <div className="text-xs text-slate-500">Notify when risk ≥ {c.min_risk}</div>
              </div>
              <span className={`chip ${c.enabled ? "sev-low" : "bg-slate-200"}`}>{c.enabled ? "on" : "off"}</span>
              <button className="btn-ghost py-1 text-sm" onClick={() => toggle(c)}>{c.enabled ? "Disable" : "Enable"}</button>
              <button className="btn-ghost py-1 text-sm text-red-500" onClick={() => remove(c)}>Delete</button>
            </div>
          ))}
        </div>
      )}

      <div className="card p-5 space-y-3">
        <div className="font-semibold text-sm">Add a channel</div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label">Name</label>
            <input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Security Slack" /></div>
          <div><label className="label">Type</label>
            <select className="input" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
              {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select></div>
          <div className="sm:col-span-2"><label className="label">Webhook URL</label>
            <input className="input font-mono text-xs" value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })}
                   placeholder="https://hooks.slack.com/services/..." /></div>
          <div><label className="label">Only notify when risk ≥</label>
            <input type="number" min="0" max="100" className="input" value={draft.min_risk}
                   onChange={(e) => setDraft({ ...draft, min_risk: +e.target.value })} /></div>
        </div>
        <div className="flex items-center gap-3">
          <button className="btn-primary" onClick={add}>Add channel</button>
          <button className="btn-ghost" onClick={test}>Send test</button>
          {msg && <span className="text-xs text-slate-600">{msg}</span>}
        </div>
      </div>

      {isGlobal && (
        <div className="card p-5 space-y-2">
          <div className="font-semibold text-sm">Public base URL (for links in alerts)</div>
          <div className="flex gap-2">
            <input className="input flex-1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
                   placeholder="https://xyberah.yourcompany.com:8443" />
            <button className="btn-ghost" onClick={saveBase}>Save</button>
          </div>
          <p className="text-xs text-slate-500">Alerts link back to the campaign using this address.</p>
        </div>
      )}
    </div>
  );
}
