import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

const TARGET_TYPES = [
  { id: "demo", label: "Demo target (no API key)" },
  { id: "openai", label: "OpenAI / compatible" },
  { id: "anthropic", label: "Anthropic" },
  { id: "ollama", label: "Ollama (local)" },
  { id: "http", label: "Custom HTTP endpoint" },
];

function Toggle({ on, set, label, desc }) {
  return (
    <button type="button" onClick={() => set(!on)}
      className={`card p-3 text-left w-full border-2 ${on ? "" : "border-slate-200"}`}
      style={on ? { borderColor: "var(--brand-primary)" } : {}}>
      <div className="flex items-center justify-between">
        <span className="font-semibold">{label}</span>
        <span className={`w-9 h-5 rounded-full relative ${on ? "" : "bg-slate-300"}`}
              style={on ? { background: "var(--brand-primary)" } : {}}>
          <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all ${on ? "left-4" : "left-0.5"}`} />
        </span>
      </div>
      <div className="text-xs text-slate-500 mt-1">{desc}</div>
    </button>
  );
}

function CheckGroup({ options, selected, onChange, labelKey = "label", idKey = "id" }) {
  const toggle = (id) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button type="button" key={o[idKey]} onClick={() => toggle(o[idKey])}
          className={`chip border ${selected.includes(o[idKey]) ? "text-white" : "bg-white border-slate-300"}`}
          style={selected.includes(o[idKey]) ? { background: "var(--brand-primary)", borderColor: "var(--brand-primary)" } : {}}>
          {o[labelKey]}
        </button>
      ))}
    </div>
  );
}

export default function NewCampaign() {
  const nav = useNavigate();
  const [catalog, setCatalog] = useState(null);
  const [err, setErr] = useState("");
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [target, setTarget] = useState({ type: "openai", model: "gpt-4.1-mini", base_url: "", system_prompt: "" });
  const [http, setHttp] = useState({ url: "", method: "POST", body: '{"message":"{{prompt}}"}', response_path: "reply", headers: "" });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  function buildTarget() {
    const t = { ...target };
    if (target.type === "demo") return { type: "demo" };
    if (target.type === "http") {
      t.http = {
        url: http.url, method: http.method,
        body: JSON.parse(http.body || "{}"),
        response_path: http.response_path,
        headers: http.headers ? JSON.parse(http.headers) : {},
      };
    }
    return t;
  }

  async function testConnection() {
    setTestResult(null); setTesting(true);
    try {
      const r = await api.post("/api/targets/test", { target: buildTarget() });
      setTestResult(r);
    } catch (e) {
      setTestResult({ ok: false, error: e.message });
    } finally { setTesting(false); }
  }
  const [tools, setTools] = useState({
    promptfoo: true, garak: false, pyrit: false, inspect: false,
    promptfoo_plugins: [], promptfoo_strategies: ["basic"], garak_probes: [],
    pyrit_attacks: ["red_teaming"], pyrit_objectives: [], pyrit_max_turns: 5,
    inspect_tasks: [], num_tests: 5, garak_generations: 5,
  });

  useEffect(() => { api.get("/api/catalog").then(setCatalog); }, []);
  const up = (patch) => setTools((t) => ({ ...t, ...patch }));

  async function submit(e) {
    e.preventDefault();
    setErr("");
    let t;
    try { t = buildTarget(); }
    catch { return setErr("HTTP body/headers must be valid JSON"); }
    try {
      const r = await api.post("/api/campaigns", {
        name, description: "", target: t, tools: { ...tools, purpose },
      });
      nav(`/campaigns/${r.id}`);
    } catch (e) { setErr(e.message); }
  }

  if (!catalog) return <p className="text-slate-500">Loading…</p>;

  return (
    <form onSubmit={submit} className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-extrabold">New campaign</h1>
      {err && <div className="rounded-lg bg-red-50 text-red-700 text-sm px-3 py-2">{err}</div>}

      <section className="card p-5 space-y-4">
        <h2 className="font-bold">1 · Basics</h2>
        <div><label className="label">Campaign name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} required /></div>
        <div><label className="label">Application purpose (steers attacks)</label>
          <input className="input" value={purpose} placeholder="e.g. Customer support assistant for an online bank"
                 onChange={(e) => setPurpose(e.target.value)} /></div>
      </section>

      <section className="card p-5 space-y-4">
        <h2 className="font-bold">2 · Target</h2>
        <div className="flex flex-wrap gap-2">
          {TARGET_TYPES.map((tt) => (
            <button type="button" key={tt.id} onClick={() => {
              setTarget({ ...target, type: tt.id });
              // Make the demo "just work": preselect garak's deterministic probes (no API key)
              if (tt.id === "demo") {
                setTools((t) => ({ ...t, promptfoo: false, garak: true, pyrit: false, inspect: false,
                  garak_probes: t.garak_probes.length ? t.garak_probes
                    : ["promptinject", "web_injection"] }));
              }
            }}
              className={`tab border ${target.type === tt.id ? "tab-active" : "border-slate-200"}`}>{tt.label}</button>
          ))}
        </div>
        {target.type === "demo" ? (
          <div className="rounded-lg border border-violet-200 bg-violet-50 p-4 text-sm">
            A built-in, deliberately-vulnerable chatbot. Needs no API key or setup — ideal for a
            first run. Pair it with <b>garak</b> probes below (promptinject, leakreplay,
            web_injection, encoding) to get findings without a grading model.
          </div>
        ) : target.type !== "http" ? (
          <div className="grid sm:grid-cols-2 gap-4">
            <div><label className="label">Model</label>
              <input className="input" value={target.model} onChange={(e) => setTarget({ ...target, model: e.target.value })} required /></div>
            {(target.type === "openai" || target.type === "ollama") && (
              <div><label className="label">Base URL (optional)</label>
                <input className="input" value={target.base_url} placeholder={target.type === "ollama" ? "http://host:11434" : "https://api.openai.com/v1"}
                       onChange={(e) => setTarget({ ...target, base_url: e.target.value })} /></div>
            )}
            <div className="sm:col-span-2"><label className="label">System prompt (optional)</label>
              <textarea className="input" rows={2} value={target.system_prompt}
                        onChange={(e) => setTarget({ ...target, system_prompt: e.target.value })} /></div>
          </div>
        ) : (
          <div className="grid sm:grid-cols-6 gap-4">
            <div className="sm:col-span-2"><label className="label">Method</label>
              <select className="input" value={http.method} onChange={(e) => setHttp({ ...http, method: e.target.value })}>
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select></div>
            <div className="sm:col-span-4"><label className="label">Endpoint URL</label>
              <input className="input" value={http.url} placeholder="https://your-app.example/chat"
                     onChange={(e) => setHttp({ ...http, url: e.target.value })} required /></div>
            <div className="sm:col-span-3"><label className="label">Response JSON path</label>
              <input className="input" value={http.response_path} placeholder="reply  or  choices.0.message.content"
                     onChange={(e) => setHttp({ ...http, response_path: e.target.value })} /></div>
            <div className="sm:col-span-3"><label className="label">Headers (JSON, optional)</label>
              <input className="input" value={http.headers} placeholder='{"Authorization":"Bearer sk-..."}'
                     onChange={(e) => setHttp({ ...http, headers: e.target.value })} /></div>
            <div className="sm:col-span-6"><label className="label">Request body (JSON, use {"{{prompt}}"} where the message goes)</label>
              <textarea className="input font-mono text-xs" rows={2} value={http.body}
                        onChange={(e) => setHttp({ ...http, body: e.target.value })} /></div>
            <div className="sm:col-span-6 flex items-center gap-3">
              <button type="button" className="btn-ghost" onClick={testConnection} disabled={testing || !http.url}>
                {testing ? "Testing…" : "Test connection"}
              </button>
              <span className="text-xs text-slate-500">Sends one sample prompt from the server to check reachability, auth and the response path.</span>
            </div>
            {testResult && (
              <div className={`sm:col-span-6 rounded-lg px-3 py-2 text-sm ${testResult.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"}`}>
                <div className="font-semibold">
                  {testResult.ok ? "✓ Connection OK" : "✗ Test failed"}
                  {testResult.status ? ` (HTTP ${testResult.status})` : ""}
                </div>
                {testResult.reply && <div className="mt-1">Extracted reply: <span className="font-mono">{testResult.reply}</span></div>}
                {testResult.error && <div className="mt-1">{testResult.error}</div>}
                {testResult.extract_error && <div className="mt-1">{testResult.extract_error}</div>}
                {testResult.tls_note && <div className="mt-1 text-amber-700">{testResult.tls_note}</div>}
                {testResult.raw && !testResult.reply && (
                  <details className="mt-1"><summary className="cursor-pointer">Raw response</summary>
                    <pre className="mt-1 bg-white/60 p-2 rounded overflow-auto max-h-40 whitespace-pre-wrap text-xs">{testResult.raw}</pre></details>
                )}
              </div>
            )}
            <p className="sm:col-span-6 text-xs text-amber-600">Inspect AI does not support custom HTTP targets; that stage will be skipped.</p>
          </div>
        )}
      </section>

      <section className="card p-5 space-y-5">
        <h2 className="font-bold">3 · Tools &amp; coverage</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          <Toggle on={tools.promptfoo} set={(v) => up({ promptfoo: v })} label="Promptfoo plugins" desc="Native red-team plugins + strategies" />
          <Toggle on={tools.garak} set={(v) => up({ garak: v })} label="garak" desc="NVIDIA LLM vulnerability probes" />
          <Toggle on={tools.pyrit} set={(v) => up({ pyrit: v })} label="PyRIT" desc="Microsoft multi-turn attack orchestration" />
          <Toggle on={tools.inspect} set={(v) => up({ inspect: v })} label="Inspect AI" desc="Agentic / tool-use / reasoning safety" />
        </div>

        {tools.promptfoo && (
          <div className="border-t pt-4 space-y-3">
            <div className="font-semibold text-sm">Promptfoo plugins</div>
            {Object.entries(catalog.promptfoo.plugins).map(([group, plugins]) => (
              <div key={group}>
                <div className="text-xs text-slate-500 mb-1">{group}</div>
                <CheckGroup options={plugins} selected={tools.promptfoo_plugins}
                  onChange={(v) => up({ promptfoo_plugins: v })} />
              </div>
            ))}
            <div className="text-xs text-slate-500 mb-1">Strategies</div>
            <CheckGroup options={catalog.promptfoo.strategies} selected={tools.promptfoo_strategies}
              onChange={(v) => up({ promptfoo_strategies: v })} />
          </div>
        )}
        {tools.garak && (
          <div className="border-t pt-4">
            <div className="font-semibold text-sm mb-1">garak probes</div>
            <CheckGroup options={catalog.garak.probes} selected={tools.garak_probes}
              onChange={(v) => up({ garak_probes: v })} />
          </div>
        )}
        {tools.pyrit && (
          <div className="border-t pt-4 space-y-2">
            <div className="font-semibold text-sm">PyRIT attacks</div>
            <CheckGroup options={catalog.pyrit.attacks} selected={tools.pyrit_attacks}
              onChange={(v) => up({ pyrit_attacks: v })} />
            <label className="label mt-2">Objectives (one per line; defaults used if empty)</label>
            <textarea className="input text-xs" rows={3}
              defaultValue={tools.pyrit_objectives.join("\n")}
              onBlur={(e) => up({ pyrit_objectives: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} />
          </div>
        )}
        {tools.inspect && (
          <div className="border-t pt-4">
            <div className="font-semibold text-sm mb-1">Inspect AI tasks</div>
            <CheckGroup options={catalog.inspect.tasks} selected={tools.inspect_tasks}
              onChange={(v) => up({ inspect_tasks: v })} />
          </div>
        )}

        <div className="border-t pt-4 grid grid-cols-2 gap-4">
          <div><label className="label">Tests per plugin</label>
            <input type="number" min="1" max="50" className="input" value={tools.num_tests}
                   onChange={(e) => up({ num_tests: +e.target.value })} /></div>
          <div><label className="label">PyRIT max turns</label>
            <input type="number" min="1" max="20" className="input" value={tools.pyrit_max_turns}
                   onChange={(e) => up({ pyrit_max_turns: +e.target.value })} /></div>
        </div>
      </section>

      <div className="flex gap-3">
        <button className="btn-primary">Create campaign</button>
        <button type="button" className="btn-ghost" onClick={() => nav("/")}>Cancel</button>
      </div>
    </form>
  );
}
