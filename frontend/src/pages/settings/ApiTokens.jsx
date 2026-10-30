import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function ApiTokens() {
  const [tokens, setTokens] = useState([]);
  const [name, setName] = useState("");
  const [created, setCreated] = useState(null);

  const load = () => api.get("/api/tokens").then(setTokens).catch(() => {});
  useEffect(() => { load(); }, []);

  async function create(e) {
    e.preventDefault();
    try {
      const r = await api.post("/api/tokens", { name });
      setCreated(r.token);
      setName("");
      load();
    } catch (e) { alert(e.message); }
  }
  const revoke = (id) => api.del(`/api/tokens/${id}`).then(load);

  return (
    <div className="space-y-5 max-w-2xl">
      <div>
        <h2 className="font-bold text-lg">API tokens (CI/CD)</h2>
        <p className="text-sm text-slate-500">Bearer tokens for automation and CI quality gates. A token acts as your account within your company.</p>
      </div>

      <form onSubmit={create} className="card p-5 space-y-3">
        <div className="flex gap-2">
          <input className="input flex-1" placeholder="Token name (e.g. github-actions)" value={name}
                 onChange={(e) => setName(e.target.value)} required />
          <button className="btn-primary">Create token</button>
        </div>
        {created && (
          <div className="rounded-lg bg-amber-50 text-amber-800 text-sm px-3 py-2">
            Copy this token now - it won't be shown again:
            <div className="font-mono break-all mt-1 bg-white rounded px-2 py-1">{created}</div>
          </div>
        )}
      </form>

      <div className="card p-5">
        <table className="w-full text-sm">
          <thead className="text-slate-500 text-left"><tr><th className="p-2">Name</th><th className="p-2">Last used</th><th className="p-2"></th></tr></thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.id} className="border-t">
                <td className="p-2">{t.name}</td>
                <td className="p-2 text-slate-500">{t.last_used ? new Date(t.last_used).toLocaleString() : "never"}</td>
                <td className="p-2 text-right"><button className="text-red-600 text-xs" onClick={() => revoke(t.id)}>Revoke</button></td>
              </tr>
            ))}
            {tokens.length === 0 && <tr><td className="p-2 text-slate-400" colSpan={3}>No tokens yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="card p-5 text-sm">
        <div className="font-semibold mb-2">Use in CI (quality gate)</div>
        <pre className="bg-slate-900 text-slate-100 p-3 rounded overflow-auto text-xs whitespace-pre-wrap">XYBERAH_URL=https://your-host:8443 XYBERAH_TOKEN=xyb_... \
SAVED_TARGET_ID=1 MAX_RISK=40 MAX_CRITICAL=0 ./ci/ci_scan.sh</pre>
        <p className="text-slate-500 mt-2">Exits non-zero if the gate fails, so it can block a merge or deploy.</p>
      </div>
    </div>
  );
}
