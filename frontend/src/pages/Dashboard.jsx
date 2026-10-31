import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { api, atLeast } from "../lib/api";
import { useApp } from "../lib/context.jsx";
import { Status, RiskGauge } from "../components/ui.jsx";

export default function Dashboard() {
  const { user } = useApp();
  const nav = useNavigate();
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);

  const [demoBusy, setDemoBusy] = useState(false);
  const load = () => api.get("/api/campaigns").then(setCampaigns).finally(() => setLoading(false));
  useEffect(() => {
    load();
    const t = setInterval(load, 5000); // keep running campaigns fresh
    return () => clearInterval(t);
  }, []);

  async function runDemo() {
    setDemoBusy(true);
    try {
      // Built-in vulnerable target + garak's deterministic probes => findings with no API key
      const r = await api.post("/api/campaigns", {
        name: "Demo scan",
        description: "Built-in vulnerable target — no API key required",
        target: { type: "demo" },
        tools: { promptfoo: false, garak: true, pyrit: false, inspect: false,
                 garak_probes: ["promptinject", "web_injection"],
                 garak_generations: 2, num_tests: 3 },
      });
      await api.post(`/api/campaigns/${r.id}/start`).catch(() => {});
      nav(`/campaigns/${r.id}`);
    } catch (e) { alert(e.message); } finally { setDemoBusy(false); }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-extrabold">Campaigns</h1>
          <p className="text-sm text-slate-500">Red-teaming and security evaluation runs for your company.</p>
        </div>
        {atLeast(user.role, "analyst") && (
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={runDemo} disabled={demoBusy}>
              {demoBusy ? "Starting…" : "⚡ Try a demo scan"}
            </button>
            <Link to="/campaigns/new" className="btn-primary">+ New campaign</Link>
          </div>
        )}
      </div>
      {atLeast(user.role, "analyst") && campaigns.length === 0 && (
        <div className="card p-4 mb-4 text-sm bg-violet-50 border-violet-200">
          New here? Click <b>⚡ Try a demo scan</b> to run a real scan against a built-in
          vulnerable chatbot — no API key or target setup needed — then explore the live
          monitoring and report before testing a production target.
        </div>
      )}

      {(() => {
        const trend = campaigns
          .filter((c) => c.status === "completed" && c.finished_at)
          .sort((a, b) => new Date(a.finished_at) - new Date(b.finished_at))
          .map((c) => ({ name: new Date(c.finished_at).toLocaleDateString(), risk: c.summary?.risk_score ?? 0 }));
        if (trend.length < 2) return null;
        return (
          <div className="card p-5 mb-4">
            <div className="text-sm font-semibold mb-2">Risk score over time</div>
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={trend} margin={{ left: -10, right: 10 }}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="risk" stroke="var(--brand-primary)" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        );
      })()}

      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : campaigns.length === 0 ? (
        <div className="card p-10 text-center text-slate-500">
          No campaigns yet.{" "}
          {atLeast(user.role, "analyst") && <Link to="/campaigns/new" style={{ color: "var(--brand-primary)" }}>Create your first one.</Link>}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {campaigns.map((c) => (
            <Link to={`/campaigns/${c.id}`} key={c.id} className="card p-5 hover:shadow-md transition flex gap-4">
              <RiskGauge score={c.summary?.risk_score || 0} band={c.summary?.risk_band || "low"} size={96} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-bold truncate">{c.name}</h3>
                  <Status value={c.status} />
                </div>
                <div className="text-xs text-slate-500 truncate">{c.target_display}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {["promptfoo", "custom", "deepteam", "garak", "pyrit", "inspect"].filter((t) => c.tools?.[t]).map((t) => (
                    <span key={t} className="chip bg-slate-100 text-slate-600">{t}</span>
                  ))}
                </div>
                {c.summary && (
                  <div className="mt-2 text-xs text-slate-600">
                    {c.summary.failed} failed / {c.summary.total} tests · {c.summary.pass_rate}% pass
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
