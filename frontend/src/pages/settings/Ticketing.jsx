import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const SEV = ["critical", "high", "medium", "low"];
const emptyGithub = { name: "", kind: "github", config: { repo: "", token: "" }, enabled: true, auto_create: false, min_severity: "high" };
const emptyJira = { name: "", kind: "jira", config: { base_url: "", email: "", api_token: "", project_key: "", issue_type: "Bug" }, enabled: true, auto_create: false, min_severity: "high" };

export default function Ticketing() {
  const [configs, setConfigs] = useState(null);
  const [draft, setDraft] = useState(emptyGithub);
  const [msg, setMsg] = useState("");

  const load = () => api.get("/api/tickets/configs").then(setConfigs).catch(() => setConfigs([]));
  useEffect(() => { load(); }, []);

  const setKind = (kind) => setDraft(kind === "github" ? { ...emptyGithub } : { ...emptyJira });
  const setConf = (patch) => setDraft((d) => ({ ...d, config: { ...d.config, ...patch } }));

  async function add() {
    setMsg("");
    try { await api.post("/api/tickets/configs", draft); setDraft(emptyGithub); load(); }
    catch (e) { setMsg(e.message); }
  }
  async function test() {
    setMsg("Testing…");
    const r = await api.post("/api/tickets/test", { kind: draft.kind, config: draft.config });
    setMsg(r.ok ? "Credentials OK ✓" : `Test failed: ${r.error || ""}`);
  }
  async function toggle(c, field) {
    await api.put(`/api/tickets/configs/${c.id}`, { ...c, config: {}, [field]: !c[field] }); load();
  }
  async function remove(c) { if (confirm(`Delete "${c.name}"?`)) { await api.del(`/api/tickets/configs/${c.id}`); load(); } }

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h2 className="font-bold text-lg">Ticketing (GitHub / Jira)</h2>
        <p className="text-sm text-slate-500">File findings as issues. Create them by hand from a finding, or auto-file above a severity when a scan finishes.</p>
      </div>

      {configs === null ? <p className="text-slate-500">Loading…</p> : configs.length > 0 && (
        <div className="space-y-2">
          {configs.map((c) => (
            <div key={c.id} className="card p-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="font-semibold">{c.name} <span className="text-xs text-slate-400">({c.kind})</span></div>
                <div className="text-xs text-slate-500 truncate">
                  {c.kind === "github" ? c.config.repo : `${c.config.base_url} · ${c.config.project_key}`}
                </div>
                <div className="text-xs text-slate-500">
                  Auto-file ≥ {c.min_severity}: <b>{c.auto_create ? "on" : "off"}</b>
                </div>
              </div>
              <span className={`chip ${c.enabled ? "sev-low" : "bg-slate-200"}`}>{c.enabled ? "on" : "off"}</span>
              <button className="btn-ghost py-1 text-xs" onClick={() => toggle(c, "enabled")}>{c.enabled ? "Disable" : "Enable"}</button>
              <button className="btn-ghost py-1 text-xs" onClick={() => toggle(c, "auto_create")}>{c.auto_create ? "Auto off" : "Auto on"}</button>
              <button className="btn-ghost py-1 text-xs text-red-500" onClick={() => remove(c)}>Delete</button>
            </div>
          ))}
        </div>
      )}

      <div className="card p-5 space-y-3">
        <div className="font-semibold text-sm">Add a tracker</div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label">Name</label>
            <input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Security issues" /></div>
          <div><label className="label">Type</label>
            <select className="input" value={draft.kind} onChange={(e) => setKind(e.target.value)}>
              <option value="github">GitHub Issues</option><option value="jira">Jira</option>
            </select></div>
        </div>

        {draft.kind === "github" ? (
          <div className="grid sm:grid-cols-2 gap-3">
            <div><label className="label">Repository (owner/name)</label>
              <input className="input font-mono text-xs" value={draft.config.repo} onChange={(e) => setConf({ repo: e.target.value })} placeholder="acme/app" /></div>
            <div><label className="label">Token (repo scope)</label>
              <input className="input font-mono text-xs" type="password" value={draft.config.token} onChange={(e) => setConf({ token: e.target.value })} placeholder="ghp_…" /></div>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-3">
            <div><label className="label">Base URL</label>
              <input className="input font-mono text-xs" value={draft.config.base_url} onChange={(e) => setConf({ base_url: e.target.value })} placeholder="https://acme.atlassian.net" /></div>
            <div><label className="label">Project key</label>
              <input className="input font-mono text-xs" value={draft.config.project_key} onChange={(e) => setConf({ project_key: e.target.value })} placeholder="SEC" /></div>
            <div><label className="label">Email</label>
              <input className="input font-mono text-xs" value={draft.config.email} onChange={(e) => setConf({ email: e.target.value })} /></div>
            <div><label className="label">API token</label>
              <input className="input font-mono text-xs" type="password" value={draft.config.api_token} onChange={(e) => setConf({ api_token: e.target.value })} /></div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={draft.auto_create} onChange={(e) => setDraft({ ...draft, auto_create: e.target.checked })} />
            Auto-file on scan completion
          </label>
          {draft.auto_create && (
            <select className="input w-auto py-1" value={draft.min_severity} onChange={(e) => setDraft({ ...draft, min_severity: e.target.value })}>
              {SEV.map((s) => <option key={s} value={s}>≥ {s}</option>)}
            </select>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button className="btn-primary" onClick={add}>Add tracker</button>
          <button className="btn-ghost" onClick={test}>Test credentials</button>
          {msg && <span className="text-xs text-slate-600">{msg}</span>}
        </div>
      </div>
    </div>
  );
}
