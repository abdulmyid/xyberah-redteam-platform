import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

const SEV_ORDER = ["critical", "high", "medium", "low"];
const SEV_LABEL = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

export default function ModelAudit() {
  const [available, setAvailable] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    api.get("/api/modelaudit/status")
      .then((r) => setAvailable(!!r.available))
      .catch(() => setAvailable(false));
  }, []);

  async function scan() {
    if (!file) return;
    setBusy(true); setError(""); setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.upload("/api/modelaudit/scan", fd);
      if (!r.ok) setError(r.error || "Scan failed");
      setResult(r);
    } catch (e) {
      setError(e.message || "Scan failed");
    } finally {
      setBusy(false);
    }
  }

  const fmtSize = (n) => {
    if (!n && n !== 0) return "";
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold">Model Audit</h1>
        <p className="text-sm text-slate-500 mt-1">
          Scan a model file (pickle, PyTorch, safetensors, Keras, GGUF, ONNX, ZIP…) for malicious
          code, unsafe deserialization and embedded exploits before you load or deploy it.
        </p>
      </div>

      {available === false && (
        <div className="card p-4 text-sm sev-high">
          The ModelAudit scanner is not installed in this image. Rebuild the backend image to enable it.
        </div>
      )}

      <div className="card p-6 space-y-4">
        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files?.[0] || null); }}
          className="border-2 border-dashed border-slate-300 rounded-xl p-8 text-center cursor-pointer hover:border-violet-400"
        >
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          {file ? (
            <div>
              <div className="font-semibold">{file.name}</div>
              <div className="text-xs text-slate-500">{fmtSize(file.size)}</div>
            </div>
          ) : (
            <div className="text-slate-500">
              <div className="font-medium">Drop a model file here, or click to choose</div>
              <div className="text-xs mt-1">Up to 300 MB</div>
            </div>
          )}
        </div>
        <div className="flex gap-3">
          <button className="btn-primary" disabled={!file || busy || available === false} onClick={scan}>
            {busy ? "Scanning…" : "Scan file"}
          </button>
          {file && !busy && (
            <button className="btn-ghost" onClick={() => { setFile(null); setResult(null); setError(""); }}>
              Clear
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="card p-4 text-sm sev-high">
          <div className="font-semibold mb-1">Scan error</div>
          <pre className="whitespace-pre-wrap text-xs">{error}</pre>
        </div>
      )}

      {result && result.ok && (
        <div className="space-y-4">
          <div className="card p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-semibold">{result.filename}</div>
                <div className="text-xs text-slate-500">{fmtSize(result.size)}</div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-extrabold">{result.total_issues}</div>
                <div className="text-xs text-slate-500">issue{result.total_issues === 1 ? "" : "s"}</div>
              </div>
            </div>
            {result.total_issues === 0 ? (
              <div className="mt-3 chip sev-low">No issues found — file looks clean</div>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {SEV_ORDER.filter((s) => result.by_severity?.[s]).map((s) => (
                  <span key={s} className={`chip sev-${s}`}>
                    {result.by_severity[s]} {SEV_LABEL[s]}
                  </span>
                ))}
              </div>
            )}
          </div>

          {result.issues?.length > 0 && (
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Severity</th>
                    <th className="px-4 py-2">Issue</th>
                    <th className="px-4 py-2">Location</th>
                  </tr>
                </thead>
                <tbody>
                  {result.issues.map((i, idx) => (
                    <tr key={idx} className="border-t border-slate-100 align-top">
                      <td className="px-4 py-3">
                        <span className={`chip sev-${i.severity}`}>{SEV_LABEL[i.severity] || i.severity}</span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium">{i.message}</div>
                        {i.rule_code && <div className="text-xs text-slate-400 mt-0.5">{i.rule_code}</div>}
                        {i.why && <div className="text-xs text-slate-500 mt-1">{i.why}</div>}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 break-all">{i.location}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
