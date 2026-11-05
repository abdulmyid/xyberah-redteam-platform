// Small helpers shared by the AI Firewall tabs.
export const VERDICT_STYLE = {
  allowed: "bg-green-100 text-green-800",
  masked: "bg-sky-100 text-sky-800",
  blocked: "bg-red-100 text-red-800",
  rate_limited: "bg-amber-100 text-amber-800",
  error: "bg-slate-200 text-slate-700",
};

export function Verdict({ value }) {
  return <span className={`chip ${VERDICT_STYLE[value] || "bg-slate-100 text-slate-600"}`}>{value?.replace("_", " ")}</span>;
}

export const KIND_LABEL = {
  injection: "Prompt injection",
  toxicity: "Toxicity",
  code: "Code generation",
  dlp: "DLP",
  keywords: "Keywords",
  regex: "Regex",
};

export const ACTION_STYLE = {
  block: "bg-red-100 text-red-800",
  mask: "bg-sky-100 text-sky-800",
  pseudonymize: "bg-violet-100 text-violet-800",
  hash: "bg-indigo-100 text-indigo-800",
  anonymize: "bg-cyan-100 text-cyan-800",
  log: "bg-slate-100 text-slate-700",
};

export const fmtTime = (d) => (d ? new Date(d.endsWith?.("Z") || d.includes?.("+") ? d : `${d}Z`).toLocaleString() : "—");

export function CopyBox({ value, label }) {
  return (
    <div>
      {label && <div className="label">{label}</div>}
      <div className="flex gap-2">
        <code className="flex-1 rounded-lg bg-slate-900 text-slate-100 px-3 py-2 text-xs break-all whitespace-pre-wrap">{value}</code>
        <button className="btn-ghost shrink-0" onClick={() => navigator.clipboard?.writeText(value)}>Copy</button>
      </div>
    </div>
  );
}
