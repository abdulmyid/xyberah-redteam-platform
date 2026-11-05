import { Fragment, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Verdict, fmtTime } from "./shared.jsx";

const PAGE = 50;

export default function Traffic() {
  const [filters, setFilters] = useState({ verdict: "", q: "", hours: 24 });
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  const [live, setLive] = useState(true);

  useEffect(() => {
    const load = () => {
      const p = new URLSearchParams({ hours: filters.hours, offset, limit: PAGE });
      if (filters.verdict) p.set("verdict", filters.verdict);
      if (filters.q.trim()) p.set("q", filters.q.trim());
      api.get(`/api/gateway/events?${p}`).then(setData).catch(() => setData({ items: [], total: 0 }));
    };
    load();
    if (!live) return undefined;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [filters, offset, live]);

  const set = (patch) => { setOffset(0); setFilters((f) => ({ ...f, ...patch })); };

  return (
    <div className="space-y-4">
      <div className="card p-4 flex flex-wrap items-end gap-3">
        <div><label className="label">Verdict</label>
          <select className="input w-auto" value={filters.verdict} onChange={(e) => set({ verdict: e.target.value })}>
            <option value="">All</option><option value="allowed">Allowed</option><option value="masked">Masked</option>
            <option value="blocked">Blocked</option><option value="rate_limited">Rate limited</option><option value="error">Error</option>
          </select></div>
        <div><label className="label">Period</label>
          <select className="input w-auto" value={filters.hours} onChange={(e) => set({ hours: +e.target.value })}>
            <option value={1}>Last hour</option><option value={24}>24 hours</option><option value={168}>7 days</option><option value={720}>30 days</option>
          </select></div>
        <div className="flex-1 min-w-[200px]"><label className="label">Search</label>
          <input className="input" placeholder="Request ID, model, client IP, consumer…" value={filters.q}
                 onChange={(e) => set({ q: e.target.value })} /></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Live</label>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr><th className="px-3 py-2">Time</th><th className="px-3 py-2">Consumer</th><th className="px-3 py-2">Model</th>
              <th className="px-3 py-2">Verdict</th><th className="px-3 py-2">Rules tripped</th><th className="px-3 py-2 text-right">Tokens</th>
              <th className="px-3 py-2 text-right">Latency</th><th className="px-3 py-2 text-right">Status</th></tr>
          </thead>
          <tbody>
            {!data ? <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-500">Loading…</td></tr>
              : data.items.length === 0 ? <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-500">No requests match.</td></tr>
              : data.items.map((e) => (
                <Fragment key={e.id}>
                  <tr className="border-t border-slate-100 cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === e.id ? null : e.id)}>
                    <td className="px-3 py-2 whitespace-nowrap">{fmtTime(e.ts)}</td>
                    <td className="px-3 py-2">{e.consumer_name || "—"}</td>
                    <td className="px-3 py-2">{e.model || "—"}{e.stream && <span className="chip bg-slate-100 ml-1">stream</span>}</td>
                    <td className="px-3 py-2"><Verdict value={e.verdict} />{e.cache_hit && <span className="chip bg-emerald-100 text-emerald-800 ml-1">cache</span>}</td>
                    <td className="px-3 py-2 text-xs text-slate-600">{(e.rules_tripped || []).join(", ") || "—"}</td>
                    <td className="px-3 py-2 text-right">{e.tokens_used}</td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">{Math.round(e.proxy_latency_ms)} ms</td>
                    <td className="px-3 py-2 text-right">{e.status_code}</td>
                  </tr>
                  {open === e.id && (
                    <tr className="bg-slate-50"><td colSpan={8} className="px-4 py-3 text-xs grid sm:grid-cols-3 gap-x-6 gap-y-1">
                      <div>Request ID: <code>{e.request_id}</code></div>
                      <div>Client IP: {e.client_ip || "—"}</div>
                      <div>Route: {e.route} → {e.provider || "—"}</div>
                      <div>Guardrails: <b>{e.guardrail_verdict}</b></div>
                      <div>DLP: <b>{e.dlp_verdict}</b></div>
                      <div>Blocked direction: {e.blocked_direction || "—"}</div>
                      <div>Prompt / completion tokens: {e.prompt_tokens} / {e.completion_tokens}</div>
                      <div>Upstream latency: {Math.round(e.upstream_latency_ms)} ms</div>
                      <div>Gateway overhead: {Math.max(0, Math.round(e.proxy_latency_ms - e.upstream_latency_ms))} ms</div>
                      {e.error && <div className="sm:col-span-3 text-red-700">Error: {e.error}</div>}
                    </td></tr>
                  )}
                </Fragment>
              ))}
          </tbody>
        </table>
      </div>
      {data && data.total > PAGE && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
          <div className="flex gap-2">
            <button className="btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
            <button className="btn-ghost" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
          </div>
        </div>
      )}
      <p className="text-xs text-slate-500">Metadata only — prompt and response text is never stored. Every record is also written to the hash-chained JSONL audit trail and forwarded to syslog/SIEM when configured.</p>
    </div>
  );
}
