import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useApp } from "../../lib/context.jsx";

const META = {
  garak: { label: "garak", desc: "NVIDIA LLM vulnerability scanner" },
  pyrit: { label: "PyRIT", desc: "Microsoft risk-identification toolkit" },
  inspect: { label: "Inspect AI", desc: "UK AISI agentic-safety evals" },
};

export default function Tools() {
  const { user } = useApp();
  const [versions, setVersions] = useState(null);
  const [busy, setBusy] = useState("");
  const [log, setLog] = useState(null);

  const load = () => api.get("/api/tools/versions").then(setVersions);
  useEffect(() => { load(); }, []);

  async function update(tool) {
    setBusy(tool); setLog(null);
    try {
      const r = await api.post(`/api/tools/${tool}/update`);
      setLog({ tool, ...r });
      await load();
    } catch (e) { setLog({ tool, ok: false, error: e.message }); }
    finally { setBusy(""); }
  }

  if (!versions) return <p className="text-slate-500">Loading…</p>;
  const isGlobal = user.role === "global_admin";

  return (
    <div className="space-y-4 max-w-2xl">
      <div>
        <h2 className="font-bold text-lg">Scanner engines</h2>
        <p className="text-sm text-slate-500">Promptfoo is the orchestrator. These scanners update from PyPI.</p>
      </div>

      {Object.entries(META).map(([tool, meta]) => {
        const v = versions[tool] || {};
        return (
          <div key={tool} className="card p-5 flex items-center gap-4">
            <div className="flex-1">
              <div className="font-semibold">{meta.label}</div>
              <div className="text-xs text-slate-500">{meta.desc}</div>
              <div className="text-sm mt-1">
                Installed <b>{v.installed || "—"}</b>
                {v.latest && <span className="text-slate-500"> · latest {v.latest}</span>}
                {v.update_available && <span className="chip sev-medium ml-2">update available</span>}
                {v.ready && !v.update_available && <span className="chip sev-low ml-2">up to date</span>}
              </div>
            </div>
            {isGlobal ? (
              <button className="btn-primary" disabled={busy === tool || !v.update_available}
                      onClick={() => update(tool)}>
                {busy === tool ? "Updating…" : v.update_available ? "Update" : "Latest"}
              </button>
            ) : <span className="text-xs text-slate-400">Global admin only</span>}
          </div>
        );
      })}

      {log && (
        <div className="card p-4 text-xs">
          <div className="font-semibold mb-1">
            {log.ok ? `Updated ${log.tool}: ${log.from || "—"} → ${log.to || "—"}` : `Update failed: ${log.error || ""}`}
          </div>
          {log.log && <pre className="bg-slate-900 text-slate-100 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap">{log.log}</pre>}
        </div>
      )}
    </div>
  );
}
