import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { api } from "../../lib/api";
import { Stat } from "../../components/ui.jsx";

const RANGES = [{ h: 1, label: "1h" }, { h: 24, label: "24h" }, { h: 168, label: "7d" }, { h: 720, label: "30d" }];

export default function Overview() {
  const [hours, setHours] = useState(24);
  const [stats, setStats] = useState(null);
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    const load = () => {
      api.get(`/api/gateway/stats?hours=${hours}`).then(setStats).catch((e) => setErr(e.message));
      api.get("/api/gateway/status").then(setStatus).catch(() => {});
    };
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [hours]);

  const h = status?.health || {};
  const v = stats?.verdicts || {};
  const pct = (x) => `${(100 * (x || 0)).toFixed(1)}%`;

  return (
    <div className="space-y-5">
      <div className="card p-4 flex flex-wrap items-center gap-4 text-sm">
        <span className={`chip ${h.reachable ? "sev-low" : "sev-critical"}`}>
          {status ? (h.reachable ? "Gateway online" : "Gateway unreachable") : "Checking…"}
        </span>
        {h.reachable && (
          <>
            <span>Rate limiter: <b>{h.limiter === "redis" ? "Redis (shared)" : "in-memory fallback"}</b></span>
            <span>Detection workers: <b>{h.workers}</b></span>
            {h.audit_dropped > 0 && <span className="text-red-700">Audit records dropped: {h.audit_dropped}</span>}
          </>
        )}
        <span className="ml-auto text-slate-500">
          Endpoint: <code>{status?.public_base_url || `https://${window.location.hostname}:8080`}/v1</code>
        </span>
      </div>

      <div className="flex items-center gap-2">
        {RANGES.map((r) => (
          <button key={r.h} onClick={() => setHours(r.h)}
            className={`tab ${hours === r.h ? "tab-active" : "hover:bg-slate-100"}`}>{r.label}</button>
        ))}
      </div>

      {err && <div className="text-sm text-red-700">{err}</div>}
      {!stats ? <p className="text-slate-500">Loading…</p> : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Requests" value={stats.total.toLocaleString()} />
            <Stat label={`Blocked (${stats.inbound_blocks} in / ${stats.outbound_blocks} out)`} value={(v.blocked || 0).toLocaleString()} tone="text-red-700" />
            <Stat label="Masked by DLP" value={(v.masked || 0).toLocaleString()} tone="text-sky-700" />
            <Stat label="Rate limited" value={(v.rate_limited || 0).toLocaleString()} tone="text-amber-700" />
            <Stat label="Latency p50 / p95 (ms)" value={`${stats.latency_ms.p50} / ${stats.latency_ms.p95}`} />
            <Stat label="Gateway overhead p50 / p95 (ms)" value={`${stats.gateway_overhead_ms.p50} / ${stats.gateway_overhead_ms.p95}`} />
            <Stat label="Cache hit rate" value={pct(stats.cache_hit_rate)} />
            <Stat label="Tokens" value={stats.tokens.toLocaleString()} />
          </div>

          <div className="grid lg:grid-cols-3 gap-4">
            <div className="card p-4 lg:col-span-2">
              <div className="font-semibold text-sm mb-2">Traffic per hour</div>
              {stats.series.length === 0 ? <p className="text-sm text-slate-500 py-10 text-center">No traffic in this period.</p> : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={stats.series.map((s) => ({ ...s, hour: s.hour.slice(11, 16) }))}>
                    <XAxis dataKey="hour" fontSize={11} />
                    <YAxis allowDecimals={false} fontSize={11} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="requests" fill="#94a3b8" name="Requests" />
                    <Bar dataKey="masked" fill="#0284c7" name="Masked" />
                    <Bar dataKey="blocked" fill="#dc2626" name="Blocked" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
            <div className="card p-4">
              <div className="font-semibold text-sm mb-2">Top rules tripped</div>
              {stats.top_rules.length === 0 ? <p className="text-sm text-slate-500">No rules tripped.</p> : (
                <ul className="space-y-2 text-sm">
                  {stats.top_rules.map((r) => (
                    <li key={r.rule} className="flex justify-between gap-2">
                      <span className="truncate">{r.rule}</span><b>{r.count}</b>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
