import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { CopyBox, fmtTime } from "./shared.jsx";

const blank = { name: "", policy_id: "", provider_ids: [], allowed_models: "", requests_per_minute: 60,
  tokens_per_minute: 0, cache_enabled: false, cache_ttl_seconds: 300, enabled: true, create_target: false, target_model: "" };

function QuickStart({ apiKey, base, model }) {
  const m = model || "gpt-4.1-mini";
  return (
    <div className="space-y-3">
      <CopyBox label="cURL (OpenAI format)" value={`curl ${base}/v1/chat/completions \\
  -H "Authorization: Bearer ${apiKey}" -H "Content-Type: application/json" \\
  -d '{"model":"${m}","messages":[{"role":"user","content":"Hello"}]}'`} />
      <CopyBox label="Python — OpenAI SDK" value={`from openai import OpenAI
client = OpenAI(base_url="${base}/v1", api_key="${apiKey}")
print(client.chat.completions.create(model="${m}", messages=[{"role": "user", "content": "Hello"}]).choices[0].message.content)`} />
      <CopyBox label="Python — Anthropic SDK" value={`import anthropic
client = anthropic.Anthropic(base_url="${base}", api_key="${apiKey}")
print(client.messages.create(model="claude-sonnet-4-5", max_tokens=256, messages=[{"role": "user", "content": "Hello"}]).content[0].text)`} />
      <p className="text-xs text-slate-500">With the default self-signed certificate, clients must trust it (or pass <code>verify=False</code> / <code>-k</code> for testing). Install a trusted certificate under Settings → TLS for production.</p>
    </div>
  );
}

export default function Consumers() {
  const [rows, setRows] = useState(null);
  const [policies, setPolicies] = useState([]);
  const [providers, setProviders] = useState([]);
  const [draft, setDraft] = useState(null);
  const [created, setCreated] = useState(null);
  const [base, setBase] = useState(`https://${window.location.hostname}:8080`);
  const [msg, setMsg] = useState("");

  const load = () => api.get("/api/gateway/consumers").then(setRows).catch(() => setRows([]));
  useEffect(() => {
    load();
    api.get("/api/gateway/policies").then(setPolicies).catch(() => {});
    api.get("/api/gateway/providers").then(setProviders).catch(() => {});
    api.get("/api/gateway/status").then((s) => s.public_base_url && setBase(s.public_base_url)).catch(() => {});
  }, []);

  const toBody = (d) => ({
    ...d, policy_id: d.policy_id ? +d.policy_id : null,
    allowed_models: typeof d.allowed_models === "string" ? d.allowed_models.split(",").map((s) => s.trim()).filter(Boolean) : d.allowed_models,
  });
  async function save() {
    setMsg("");
    try {
      if (draft.id) { await api.put(`/api/gateway/consumers/${draft.id}`, toBody(draft)); }
      else { const r = await api.post("/api/gateway/consumers", toBody(draft)); setCreated(r); }
      setDraft(null); load();
    } catch (e) { setMsg(e.message); }
  }
  async function rotate(c) {
    if (!confirm(`Issue a new key for "${c.name}"? The current key stops working within seconds.`)) return;
    setCreated(await api.post(`/api/gateway/consumers/${c.id}/rotate`)); load();
  }
  async function toggle(c) { await api.put(`/api/gateway/consumers/${c.id}`, { ...c, enabled: !c.enabled }); load(); }
  async function remove(c) { if (confirm(`Delete key "${c.name}"? Apps using it will get 401.`)) { await api.del(`/api/gateway/consumers/${c.id}`); load(); } }
  const toggleProvider = (id) => setDraft((d) => ({ ...d, provider_ids: d.provider_ids.includes(id) ? d.provider_ids.filter((x) => x !== id) : [...d.provider_ids, id] }));
  const policyName = (id) => policies.find((p) => p.id === id)?.name || "— none (no inspection) —";

  return (
    <div className="space-y-5">
      {created && (
        <div className="card p-5 space-y-3 border-emerald-300 bg-emerald-50">
          <div className="font-semibold">Key for “{created.name}” — copy it now, it will not be shown again.</div>
          <CopyBox value={created.api_key} />
          {created.saved_target_id && <p className="text-sm">A red-team target <b>“AI Firewall · {created.name}”</b> was saved — pick it under New campaign to attack your firewall.</p>}
          <QuickStart apiKey={created.api_key} base={base} model={created.allowed_models?.[0]} />
          <button className="btn-ghost" onClick={() => setCreated(null)}>Done</button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">Each application gets its own key, policy, provider routing and limits.</p>
        {!draft && <button className="btn-primary" onClick={() => setDraft({ ...blank, policy_id: policies[0]?.id || "" })}>+ New consumer key</button>}
      </div>

      {draft && (
        <div className="card p-5 space-y-4 border-violet-300">
          <div className="grid sm:grid-cols-2 gap-3">
            <div><label className="label">Application name</label>
              <input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Customer support bot" /></div>
            <div><label className="label">Policy</label>
              <select className="input" value={draft.policy_id || ""} onChange={(e) => setDraft({ ...draft, policy_id: e.target.value })}>
                <option value="">— none (no inspection) —</option>
                {policies.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select></div>
            <div className="sm:col-span-2"><label className="label">Upstream providers (first match per API format is used)</label>
              {providers.length === 0 ? <p className="text-sm text-amber-700">Add an upstream provider first.</p> : (
                <div className="flex flex-wrap gap-4 text-sm">
                  {providers.map((p) => (
                    <label key={p.id} className="flex items-center gap-2"><input type="checkbox" checked={draft.provider_ids.includes(p.id)} onChange={() => toggleProvider(p.id)} /> {p.name} <span className="text-slate-400">({p.kind})</span></label>
                  ))}
                </div>
              )}</div>
            <div className="sm:col-span-2"><label className="label">Allowed models (comma separated, blank = any)</label>
              <input className="input" value={Array.isArray(draft.allowed_models) ? draft.allowed_models.join(", ") : draft.allowed_models}
                     onChange={(e) => setDraft({ ...draft, allowed_models: e.target.value })} placeholder="gpt-4.1-mini, claude-sonnet-4-5" /></div>
            <div><label className="label">Requests per minute (0 = unlimited)</label>
              <input type="number" min="0" className="input" value={draft.requests_per_minute} onChange={(e) => setDraft({ ...draft, requests_per_minute: +e.target.value })} /></div>
            <div><label className="label">Tokens per minute (0 = unlimited)</label>
              <input type="number" min="0" className="input" value={draft.tokens_per_minute} onChange={(e) => setDraft({ ...draft, tokens_per_minute: +e.target.value })} /></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.cache_enabled} onChange={(e) => setDraft({ ...draft, cache_enabled: e.target.checked })} /> Cache identical requests</label>
            {draft.cache_enabled && (
              <div><label className="label">Cache TTL (seconds)</label>
                <input type="number" min="1" className="input w-32" value={draft.cache_ttl_seconds} onChange={(e) => setDraft({ ...draft, cache_ttl_seconds: +e.target.value })} /></div>
            )}
            {!draft.id && (
              <div className="sm:col-span-2 rounded-lg bg-slate-50 p-3 space-y-2">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.create_target} onChange={(e) => setDraft({ ...draft, create_target: e.target.checked })} /> Also save as a red-team target, so campaigns can attack this firewall</label>
                {draft.create_target && <input className="input" placeholder="Model to use, e.g. gpt-4.1-mini" value={draft.target_model} onChange={(e) => setDraft({ ...draft, target_model: e.target.value })} />}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button className="btn-primary" onClick={save} disabled={!draft.name.trim()}>{draft.id ? "Save" : "Create key"}</button>
            <button className="btn-ghost" onClick={() => setDraft(null)}>Cancel</button>
            {msg && <span className="text-sm text-red-700">{msg}</span>}
          </div>
        </div>
      )}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr><th className="px-3 py-2">Application</th><th className="px-3 py-2">Key</th><th className="px-3 py-2">Policy</th>
              <th className="px-3 py-2">Limits</th><th className="px-3 py-2">Last used</th><th className="px-3 py-2"></th></tr>
          </thead>
          <tbody>
            {rows === null ? <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-500">Loading…</td></tr>
              : rows.length === 0 ? <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-500">No consumer keys yet.</td></tr>
              : rows.map((c) => (
                <tr key={c.id} className={`border-t border-slate-100 ${c.enabled ? "" : "opacity-50"}`}>
                  <td className="px-3 py-2 font-medium">{c.name}{c.cache_enabled && <span className="chip bg-emerald-100 text-emerald-800 ml-2">cache</span>}</td>
                  <td className="px-3 py-2"><code>{c.key_prefix}…</code></td>
                  <td className="px-3 py-2">{policyName(c.policy_id)}</td>
                  <td className="px-3 py-2 text-xs">{c.requests_per_minute || "∞"} req/min · {c.tokens_per_minute || "∞"} tok/min</td>
                  <td className="px-3 py-2 text-xs">{fmtTime(c.last_used_at)}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button className="text-xs underline mr-3" onClick={() => setDraft({ ...c, policy_id: c.policy_id || "" })}>Edit</button>
                    <button className="text-xs underline mr-3" onClick={() => toggle(c)}>{c.enabled ? "Disable" : "Enable"}</button>
                    <button className="text-xs underline mr-3" onClick={() => rotate(c)}>Rotate key</button>
                    <button className="text-xs underline text-red-700" onClick={() => remove(c)}>Delete</button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
