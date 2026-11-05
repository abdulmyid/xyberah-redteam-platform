import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const KINDS = {
  openai: { label: "OpenAI", url: "https://api.openai.com/v1 (default)" },
  anthropic: { label: "Anthropic", url: "https://api.anthropic.com (default)" },
  openai_compatible: { label: "OpenAI-compatible (vLLM, Ollama, OpenRouter, LiteLLM…)", url: "http://10.0.0.5:8000/v1" },
  azure_openai: { label: "Azure OpenAI", url: "https://<resource>.openai.azure.com/openai/deployments/<deployment>" },
};
const blank = { name: "", kind: "openai", base_url: "", api_key: "", api_version: "", model_map: {}, timeout_seconds: 120, enabled: true };
const mapToText = (m) => Object.entries(m || {}).map(([k, v]) => `${k}=${v}`).join("\n");
const textToMap = (t) => Object.fromEntries(t.split("\n").map((l) => l.split("=").map((s) => s.trim())).filter(([k, v]) => k && v));

export default function Providers() {
  const [rows, setRows] = useState(null);
  const [draft, setDraft] = useState(null);
  const [mapText, setMapText] = useState("");
  const [msg, setMsg] = useState("");

  const load = () => api.get("/api/gateway/providers").then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const edit = (p) => { setDraft({ ...blank, ...p, api_key: "" }); setMapText(mapToText(p.model_map)); setMsg(""); };
  async function save() {
    setMsg("");
    const body = { ...draft, model_map: textToMap(mapText) };
    try {
      if (draft.id) await api.put(`/api/gateway/providers/${draft.id}`, body);
      else await api.post("/api/gateway/providers", body);
      setDraft(null); load();
    } catch (e) { setMsg(e.message); }
  }
  async function remove(p) { if (confirm(`Delete provider "${p.name}"? Keys routed to it will lose it.`)) { await api.del(`/api/gateway/providers/${p.id}`); load(); } }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">Real model endpoints behind the firewall. Provider API keys are encrypted at rest and never exposed to clients.</p>
        {!draft && <button className="btn-primary" onClick={() => edit(blank)}>+ Add provider</button>}
      </div>

      {draft && (
        <div className="card p-5 space-y-3 border-violet-300">
          <div className="grid sm:grid-cols-2 gap-3">
            <div><label className="label">Name</label>
              <input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="OpenAI production" /></div>
            <div><label className="label">Type</label>
              <select className="input" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select></div>
            <div className="sm:col-span-2"><label className="label">Base URL</label>
              <input className="input" value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} placeholder={KINDS[draft.kind].url} /></div>
            <div><label className="label">API key {draft.id && <span className="text-slate-400 font-normal">(blank = keep current)</span>}</label>
              <input type="password" autoComplete="new-password" className="input" value={draft.api_key} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} /></div>
            {draft.kind === "azure_openai" ? (
              <div><label className="label">API version</label>
                <input className="input" value={draft.api_version} onChange={(e) => setDraft({ ...draft, api_version: e.target.value })} placeholder="2024-10-21" /></div>
            ) : (
              <div><label className="label">Upstream timeout (seconds)</label>
                <input type="number" min="5" max="900" className="input" value={draft.timeout_seconds} onChange={(e) => setDraft({ ...draft, timeout_seconds: +e.target.value })} /></div>
            )}
            <div className="sm:col-span-2"><label className="label">Model aliases (one per line: alias=real-model)</label>
              <textarea className="input h-20 font-mono text-xs" value={mapText} onChange={(e) => setMapText(e.target.value)} placeholder={"fast=gpt-4.1-mini\nsmart=gpt-4.1"} />
              <p className="text-xs text-slate-500 mt-1">Clients call the alias; the gateway rewrites it to the real model, so you can switch models without client changes.</p></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> Enabled</label>
          </div>
          <div className="flex items-center gap-3">
            <button className="btn-primary" onClick={save} disabled={!draft.name.trim()}>Save</button>
            <button className="btn-ghost" onClick={() => setDraft(null)}>Cancel</button>
            {msg && <span className="text-sm text-red-700">{msg}</span>}
          </div>
        </div>
      )}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr><th className="px-3 py-2">Name</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Endpoint</th>
              <th className="px-3 py-2">Aliases</th><th className="px-3 py-2">Key</th><th className="px-3 py-2"></th></tr>
          </thead>
          <tbody>
            {rows === null ? <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-500">Loading…</td></tr>
              : rows.length === 0 ? <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-500">No providers yet.</td></tr>
              : rows.map((p) => (
                <tr key={p.id} className={`border-t border-slate-100 ${p.enabled ? "" : "opacity-50"}`}>
                  <td className="px-3 py-2 font-medium">{p.name}</td>
                  <td className="px-3 py-2">{KINDS[p.kind]?.label.split(" (")[0] || p.kind}</td>
                  <td className="px-3 py-2 text-xs">{p.base_url || "default"}</td>
                  <td className="px-3 py-2 text-xs">{Object.keys(p.model_map || {}).join(", ") || "—"}</td>
                  <td className="px-3 py-2">{p.has_key ? <span className="chip sev-low">set</span> : <span className="chip bg-slate-200">none</span>}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button className="text-xs underline mr-3" onClick={() => edit(p)}>Edit</button>
                    <button className="text-xs underline text-red-700" onClick={() => remove(p)}>Delete</button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
