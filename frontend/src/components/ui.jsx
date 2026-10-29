export function Severity({ level }) {
  return <span className={`chip sev-${level}`}>{level}</span>;
}

const STATUS_STYLE = {
  running: "bg-blue-100 text-blue-800", queued: "bg-blue-100 text-blue-800",
  paused: "bg-amber-100 text-amber-800", completed: "bg-green-100 text-green-800",
  stopped: "bg-slate-200 text-slate-700", failed: "bg-red-100 text-red-800",
  draft: "bg-slate-100 text-slate-600", stopping: "bg-amber-100 text-amber-800",
};

export function Status({ value }) {
  return <span className={`chip ${STATUS_STYLE[value] || "bg-slate-100 text-slate-600"}`}>{value}</span>;
}

export function RiskGauge({ score = 0, band = "low", size = 120 }) {
  const r = size / 2 - 10;
  const c = 2 * Math.PI * r;
  const color = { critical: "#b91c1c", high: "#ea580c", medium: "#d97706", low: "#16a34a" }[band];
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e2e8f0" strokeWidth="12" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="12"
        strokeDasharray={`${(c * score) / 100} ${c}`} strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="48%" textAnchor="middle" fontSize="26" fontWeight="800" fill="#0f172a">{score}</text>
      <text x="50%" y="64%" textAnchor="middle" fontSize="10" fill="#64748b">risk /100</text>
    </svg>
  );
}

export function Stat({ label, value, tone }) {
  return (
    <div className="card p-4">
      <div className={`text-2xl font-extrabold ${tone || ""}`}>{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
