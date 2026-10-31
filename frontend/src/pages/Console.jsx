import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

export default function Console() {
  const [saved, setSaved] = useState([]);
  const [targetId, setTargetId] = useState("demo");
  const [prompt, setPrompt] = useState("");
  const [turns, setTurns] = useState([]);   // {prompt, output, ok, error, saved}
  const [busy, setBusy] = useState(false);
  const [sets, setSets] = useState([]);
  const [msg, setMsg] = useState("");
  const endRef = useRef(null);

  useEffect(() => {
    api.get("/api/targets/saved").then(setSaved).catch(() => {});
    api.get("/api/prompts").then(setSets).catch(() => {});
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns]);

  async function resolveTarget() {
    if (targetId === "demo") return { type: "demo" };
    const { target } = await api.get(`/api/targets/saved/${targetId}`);
    return target;
  }

  async function send() {
    if (!prompt.trim()) return;
    const text = prompt;
    setBusy(true); setMsg("");
    try {
      const target = await resolveTarget();
      const r = await api.post("/api/console/send", { target, prompt: text });
      setTurns((t) => [...t, { prompt: text, output: r.output || "", ok: r.ok, error: r.error }]);
      setPrompt("");
    } catch (e) {
      setTurns((t) => [...t, { prompt: text, output: "", ok: false, error: e.message }]);
    } finally { setBusy(false); }
  }

  const toggleSave = (i) =>
    setTurns((t) => t.map((x, j) => (j === i ? { ...x, saved: !x.saved } : x)));

  const marked = turns.filter((t) => t.saved).map((t) => t.prompt);

  async function saveToLibrary() {
    if (!marked.length) return setMsg("Star some prompts first.");
    const choice = window.prompt(
      `Save ${marked.length} prompt(s). Enter a NEW set name, or an existing set id to append to:\n` +
      sets.map((s) => `  #${s.id} — ${s.name}`).join("\n"),
      ""
    );
    if (!choice) return;
    try {
      const existing = sets.find((s) => String(s.id) === choice.replace("#", "").trim());
      if (existing) {
        const full = await api.get(`/api/prompts/${existing.id}`);
        await api.put(`/api/prompts/${existing.id}`, {
          name: full.name, description: full.description,
          prompts: [...(full.prompts || []), ...marked], grading: full.grading,
        });
        setMsg(`Appended ${marked.length} to "${existing.name}".`);
      } else {
        await api.post("/api/prompts", {
          name: choice, description: "Saved from the red-team console",
          prompts: marked, grading: { use_rubric: true, rubric: "", must_not_contain: [], must_contain: [], severity: "high" },
        });
        setMsg(`Created set "${choice}" with ${marked.length} prompts.`);
      }
      api.get("/api/prompts").then(setSets).catch(() => {});
      setTurns((t) => t.map((x) => ({ ...x, saved: false })));
    } catch (e) { setMsg(e.message); }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-extrabold">Red-team console</h1>
        <p className="text-sm text-slate-500 mt-1">
          Probe a target by hand, one prompt at a time. Star the prompts that land and save them to a set.
          Each send is independent (single-turn).
        </p>
      </div>

      <div className="card p-4 flex flex-wrap items-center gap-3">
        <label className="label mb-0">Target</label>
        <select className="input w-auto" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
          <option value="demo">Demo target (no API key)</option>
          {saved.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.type})</option>)}
        </select>
        {saved.length === 0 && <span className="text-xs text-slate-500">Save targets in New Campaign to use them here.</span>}
        <div className="ml-auto">
          <button className="btn-ghost py-1 text-sm" disabled={!marked.length} onClick={saveToLibrary}>
            ★ Save {marked.length || ""} to library
          </button>
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="max-h-[420px] overflow-auto p-4 space-y-4">
          {turns.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">Send a prompt to begin.</p>
          ) : turns.map((t, i) => (
            <div key={i} className="space-y-1">
              <div className="flex items-start gap-2">
                <span className="chip bg-violet-100 text-violet-700 shrink-0">you</span>
                <div className="flex-1 text-sm whitespace-pre-wrap">{t.prompt}</div>
                <button className={`shrink-0 text-lg ${t.saved ? "text-amber-500" : "text-slate-300 hover:text-amber-400"}`}
                        title="Save this prompt" onClick={() => toggleSave(i)}>★</button>
              </div>
              <div className="flex items-start gap-2">
                <span className={`chip shrink-0 ${t.ok ? "bg-slate-100 text-slate-600" : "sev-high"}`}>target</span>
                <pre className="flex-1 text-sm whitespace-pre-wrap bg-slate-50 rounded p-2 border">{t.ok ? t.output : (t.error || "failed")}</pre>
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>
        <div className="border-t p-3 flex gap-2">
          <textarea className="input flex-1 font-mono text-xs" rows={2} value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); }}
                    placeholder="Type an attack prompt…  (Ctrl/⌘+Enter to send)" />
          <button className="btn-primary" disabled={busy || !prompt.trim()} onClick={send}>
            {busy ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
      {msg && <div className="text-sm text-slate-600">{msg}</div>}
    </div>
  );
}
