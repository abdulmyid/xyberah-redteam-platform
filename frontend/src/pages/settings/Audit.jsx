import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useApp } from "../../lib/context.jsx";

export default function Audit() {
  const { user } = useApp();
  const [rows, setRows] = useState([]);
  const [verify, setVerify] = useState(null);

  useEffect(() => { api.get("/api/audit").then(setRows); }, []);

  async function check() {
    setVerify(await api.get("/api/audit/verify"));
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-bold text-lg">Audit log</h2>
          <p className="text-sm text-slate-500">Every change is recorded and hash-chained — tampering is detectable.</p>
        </div>
        {user.role === "global_admin" && (
          <div className="flex items-center gap-2">
            {verify && (
              <span className={`chip ${verify.valid ? "sev-low" : "sev-critical"}`}>
                {verify.valid ? `chain valid (${verify.checked})` : `BROKEN at #${verify.broken_at}`}
              </span>
            )}
            <button className="btn-ghost" onClick={check}>Verify integrity</button>
          </div>
        )}
      </div>

      <div className="card overflow-auto">
        <table className="w-full text-xs">
          <thead className="text-slate-500 text-left">
            <tr><th className="p-2">Time</th><th className="p-2">User</th><th className="p-2">Action</th><th className="p-2">Status</th><th className="p-2">IP</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t">
                <td className="p-2 whitespace-nowrap">{new Date(r.ts).toLocaleString()}</td>
                <td className="p-2">{r.user_email || "—"}</td>
                <td className="p-2 font-mono">{r.method} {r.path}</td>
                <td className="p-2">
                  <span className={`chip ${r.status < 300 ? "sev-low" : r.status < 500 ? "sev-medium" : "sev-critical"}`}>{r.status}</span>
                </td>
                <td className="p-2 text-slate-500">{r.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
