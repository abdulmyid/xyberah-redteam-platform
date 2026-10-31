import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useApp } from "../../lib/context.jsx";

export default function Governance() {
  const { user } = useApp();
  const isGlobal = user.role === "global_admin";
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState(isGlobal ? "" : user.company_id);
  const [g, setG] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (isGlobal) api.get("/api/companies").then((cs) => {
      setCompanies(cs);
      if (cs.length && !companyId) setCompanyId(cs[0].id);
    }).catch(() => {});
  }, []);

  const load = (cid) => {
    const qs = cid ? `?company_id=${cid}` : "";
    api.get(`/api/governance${qs}`).then(setG).catch((e) => setMsg(e.message));
  };
  useEffect(() => { if (companyId || !isGlobal) load(companyId); }, [companyId]);

  const set = (patch) => setG((x) => ({ ...x, ...patch }));

  async function save() {
    setMsg("");
    const qs = isGlobal && companyId ? `?company_id=${companyId}` : "";
    try {
      const r = await api.put(`/api/governance${qs}`, {
        redact_findings: g.redact_findings, retention_days: g.retention_days,
        monthly_cost_budget: g.monthly_cost_budget, monthly_token_budget: g.monthly_token_budget,
        budget_enforce: g.budget_enforce,
      });
      setG(r); setMsg("Saved ✓");
    } catch (e) { setMsg(e.message); }
  }

  const u = g?.usage || {};
  const pct = (used, budget) => (budget > 0 ? Math.min(100, Math.round((100 * used) / budget)) : 0);

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h2 className="font-bold text-lg">Data governance</h2>
        <p className="text-sm text-slate-500">Redaction, retention, and spend controls for this company's data.</p>
      </div>

      {isGlobal && (
        <div className="card p-4">
          <label className="label">Company</label>
          <select className="input w-auto" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      )}

      {!g ? <p className="text-slate-500">Loading…</p> : (
        <>
          <div className="card p-5 space-y-3">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" checked={g.redact_findings} onChange={(e) => set({ redact_findings: e.target.checked })} />
              Redact PII &amp; secrets in stored findings
            </label>
            <p className="text-xs text-slate-500">
              When on, emails, card/SSN numbers, API keys, tokens and private keys are scrubbed from
              finding prompts/responses before they are saved. Applies to new findings.
            </p>
          </div>

          <div className="card p-5 space-y-2">
            <label className="label">Retention — auto-delete campaigns older than (days)</label>
            <input type="number" min="0" className="input w-40" value={g.retention_days}
                   onChange={(e) => set({ retention_days: +e.target.value })} />
            <p className="text-xs text-slate-500">0 = keep forever. Finished campaigns past this age (and their findings) are deleted hourly.</p>
          </div>

          <div className="card p-5 space-y-4">
            <div className="font-semibold text-sm">Monthly budgets ({u.month})</div>
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="label">Cost budget (USD, 0 = none)</label>
                <input type="number" min="0" step="0.01" className="input" value={g.monthly_cost_budget}
                       onChange={(e) => set({ monthly_cost_budget: +e.target.value })} />
                <div className="text-xs text-slate-500 mt-1">Used: ${u.cost ?? 0}{g.monthly_cost_budget > 0 && ` / $${g.monthly_cost_budget} (${pct(u.cost, g.monthly_cost_budget)}%)`}</div>
              </div>
              <div>
                <label className="label">Token budget (0 = none)</label>
                <input type="number" min="0" className="input" value={g.monthly_token_budget}
                       onChange={(e) => set({ monthly_token_budget: +e.target.value })} />
                <div className="text-xs text-slate-500 mt-1">Used: {u.tokens ?? 0}{g.monthly_token_budget > 0 && ` / ${g.monthly_token_budget} (${pct(u.tokens, g.monthly_token_budget)}%)`}</div>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={g.budget_enforce} onChange={(e) => set({ budget_enforce: e.target.checked })} />
              Block new campaigns when a budget is exceeded
            </label>
            {u.over_budget && <div className="chip sev-high">Over budget this month</div>}
          </div>

          <div className="flex items-center gap-3">
            <button className="btn-primary" onClick={save}>Save governance settings</button>
            {msg && <span className="text-sm text-slate-600">{msg}</span>}
          </div>
        </>
      )}
    </div>
  );
}
