import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";

const TARGET_TYPES = [
  { id: "demo", label: "Demo target (no API key)" },
  { id: "openai", label: "OpenAI / compatible" },
  { id: "anthropic", label: "Anthropic" },
  { id: "ollama", label: "Ollama (local)" },
  { id: "google", label: "Google Gemini" },
  { id: "azure", label: "Azure OpenAI" },
  { id: "bedrock", label: "AWS Bedrock" },
  { id: "huggingface", label: "Hugging Face" },
  { id: "http", label: "Custom HTTP endpoint" },
  { id: "browser", label: "Web chat UI (browser)" },
  { id: "mcp", label: "MCP / tool-calling agent" },
];

// --- Parse a pasted `curl` command into method/url/headers/body -------------
function tokenizeCurl(input) {
  const s = input.replace(/\\\r?\n/g, " ").replace(/^\s*curl\s+/, "curl ").trim();
  const tokens = [];
  let i = 0;
  while (i < s.length) {
    while (i < s.length && /\s/.test(s[i])) i++;
    if (i >= s.length) break;
    let tok = "";
    if (s[i] === "'" || s[i] === '"') {
      const q = s[i++];
      while (i < s.length && s[i] !== q) {
        if (s[i] === "\\" && q === '"' && i + 1 < s.length) { tok += s[i + 1]; i += 2; }
        else tok += s[i++];
      }
      i++;
    } else {
      while (i < s.length && !/\s/.test(s[i])) {
        if (s[i] === "\\" && i + 1 < s.length) { tok += s[i + 1]; i += 2; }
        else tok += s[i++];
      }
    }
    tokens.push(tok);
  }
  return tokens;
}

function parseCurl(input) {
  const t = tokenizeCurl(input);
  let url = "", method = "", body = "";
  const headers = {}, dataParts = [];
  for (let i = 0; i < t.length; i++) {
    const a = t[i];
    if (a === "curl") continue;
    else if (a === "-X" || a === "--request") method = (t[++i] || "").toUpperCase();
    else if (a === "-H" || a === "--header") {
      const h = t[++i] || ""; const idx = h.indexOf(":");
      if (idx > 0) headers[h.slice(0, idx).trim()] = h.slice(idx + 1).trim();
    } else if (["-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"].includes(a)) {
      dataParts.push(t[++i] || "");
    } else if (a === "--url") url = t[++i] || "";
    else if (a === "-u" || a === "--user") headers["Authorization"] = "Basic " + btoa(t[++i] || "");
    else if (a === "-b" || a === "--cookie") headers["Cookie"] = t[++i] || "";
    else if (/^https?:\/\//i.test(a)) url = a;
  }
  body = dataParts.join("&");
  if (!method) method = dataParts.length ? "POST" : "GET";
  return { url, method, headers, body };
}

// Insert {{prompt}} into the most likely "message" field of a JSON body.
function injectPromptPlaceholder(bodyStr) {
  try {
    const obj = JSON.parse(bodyStr);
    const keyRe = /^(content|message|prompt|text|input|query|q|user_message|question)$/i;
    const matches = [];
    const walk = (o) => {
      if (Array.isArray(o)) o.forEach(walk);
      else if (o && typeof o === "object") {
        for (const k of Object.keys(o)) {
          if (keyRe.test(k) && typeof o[k] === "string") matches.push([o, k]);
          walk(o[k]);
        }
      }
    };
    walk(obj);
    if (matches.length) { const [p, k] = matches[matches.length - 1]; p[k] = "{{prompt}}"; }
    return { body: JSON.stringify(obj, null, 2), replaced: matches.length > 0 };
  } catch { return { body: bodyStr, replaced: false }; }
}

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
  const [curlText, setCurlText] = useState("");
  const [curlMsg, setCurlMsg] = useState("");
  const [browser, setBrowser] = useState({
    url: "", input_selector: "textarea[data-testid='chat-input']",
    send_button_selector: "button[data-testid='send-button']",
    response_bubble_selector: "[data-message-author-role='assistant']",
    streaming_indicator_selector: "button[aria-label='Stop generating']",
    new_chat_selector: "", setup_steps: [], session_id: null,
  });
  const [mcp, setMcp] = useState({ base_provider: "openai", servers: [{ url: "", headers: "" }] });
  const [needsLogin, setNeedsLogin] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [sessMsg, setSessMsg] = useState("");

  useEffect(() => { api.get("/api/targets/browser-sessions").then(setSessions).catch(() => {}); }, []);

  async function uploadSession(file) {
    setSessMsg("Uploading…");
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await api.upload(`/api/targets/browser-session?name=${encodeURIComponent(file.name)}`, fd);
      const list = await api.get("/api/targets/browser-sessions");
      setSessions(list);
      setBrowser((b) => ({ ...b, session_id: r.id }));
      setSessMsg(`Saved session "${r.name}" and selected it.`);
    } catch (e) { setSessMsg(e.message); }
  }

  const STEP_ACTIONS = ["goto", "fill", "type", "click", "press", "waitForSelector", "waitForURL", "sleep"];
  const addStep = () => setBrowser((b) => ({ ...b, setup_steps: [...b.setup_steps, { action: "goto", selector: "", value: "", url: "", ms: 0 }] }));
  const setStep = (i, patch) => setBrowser((b) => ({ ...b, setup_steps: b.setup_steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) }));
  const delStep = (i) => setBrowser((b) => ({ ...b, setup_steps: b.setup_steps.filter((_, j) => j !== i) }));

  function buildTarget() {
    const t = { ...target };
    if (target.type === "demo") return { type: "demo" };
    if (target.type === "browser") return { type: "browser", browser: { ...browser } };
    if (target.type === "mcp") {
      return {
        type: "mcp", model: target.model, base_url: target.base_url || "", system_prompt: target.system_prompt,
        mcp: {
          base_provider: mcp.base_provider,
          servers: mcp.servers.filter((sv) => sv.url.trim()).map((sv) => ({
            url: sv.url.trim(), headers: sv.headers ? JSON.parse(sv.headers) : {},
          })),
        },
      };
    }
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

  function applyCurl() {
    setCurlMsg("");
    if (!curlText.trim()) return;
    try {
      const parsed = parseCurl(curlText);
      if (!parsed.url) { setCurlMsg("Could not find a URL in that curl command."); return; }
      const { body, replaced } = injectPromptPlaceholder(parsed.body || "");
      setHttp({
        url: parsed.url,
        method: parsed.method === "GET" ? "GET" : "POST",
        headers: Object.keys(parsed.headers).length ? JSON.stringify(parsed.headers) : "",
        body: body || '{"message":"{{prompt}}"}',
        response_path: http.response_path,
      });
      setTestResult(null);
      setCurlMsg(replaced
        ? "Parsed ✓ — {{prompt}} was inserted into the message field. Set the response path, then Test connection."
        : "Parsed ✓ — now replace your test message in the body with {{prompt}}, set the response path, then Test connection.");
    } catch {
      setCurlMsg("Could not parse that curl command.");
    }
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
    promptfoo: true, garak: false, pyrit: false, inspect: false, custom: false,
    promptfoo_plugins: [], promptfoo_strategies: ["basic"], garak_probes: [],
    pyrit_attacks: ["red_teaming"], pyrit_objectives: [], pyrit_max_turns: 5,
    inspect_tasks: [], num_tests: 5, garak_generations: 5, prompt_set_id: null,
    indirect_var: "context",
    deepteam: false, deepteam_vulnerabilities: [], deepteam_attacks: ["PromptInjection"],
    deepteam_attacks_per_vuln: 2,
  });

  useEffect(() => { api.get("/api/catalog").then(setCatalog); }, []);

  // Prompt-set library for the "Custom prompts" engine
  const [promptSets, setPromptSets] = useState([]);
  const [searchParams] = useSearchParams();
  useEffect(() => { api.get("/api/prompts").then(setPromptSets).catch(() => {}); }, []);
  useEffect(() => {
    const pid = searchParams.get("prompt_set");
    if (pid) setTools((t) => ({ ...t, custom: true, prompt_set_id: +pid }));
  }, [searchParams]);

  const [savedTargets, setSavedTargets] = useState([]);
  const [selectedSaved, setSelectedSaved] = useState("");
  const loadSavedList = () => api.get("/api/targets/saved").then(setSavedTargets).catch(() => {});
  useEffect(() => { loadSavedList(); }, []);

  async function loadSavedTarget(id) {
    if (!id) return;
    try {
      const { target: cfg } = await api.get(`/api/targets/saved/${id}`);
      setTarget({ type: cfg.type, model: cfg.model || "", base_url: cfg.base_url || "", system_prompt: cfg.system_prompt || "" });
      if (cfg.type === "http" && cfg.http) {
        setHttp({ url: cfg.http.url, method: cfg.http.method, body: JSON.stringify(cfg.http.body, null, 2),
                  response_path: cfg.http.response_path,
                  headers: Object.keys(cfg.http.headers || {}).length ? JSON.stringify(cfg.http.headers) : "" });
      }
      if (cfg.type === "browser" && cfg.browser) {
        setBrowser({ ...browser, ...cfg.browser });
        setNeedsLogin((cfg.browser.setup_steps || []).length > 0);
      }
      setTestResult(null);
    } catch (e) { alert(e.message); }
  }

  async function saveCurrentTarget() {
    let t;
    try { t = buildTarget(); } catch { return alert("Fix the target first (the HTTP body/headers must be valid JSON)."); }
    const name = window.prompt("Name this saved target:", target.type === "http" ? (http.url || "HTTP target") : target.type);
    if (!name) return;
    try { await api.post("/api/targets/saved", { name, target: t }); await loadSavedList(); alert(`Saved “${name}”.`); }
    catch (e) { alert(e.message); }
  }
  const up = (patch) => setTools((t) => ({ ...t, ...patch }));
  const [schedule, setSchedule] = useState({ enabled: false, freq: { kind: "daily", at: "02:00", minutes: 1440, day: 0 }, report_emails: "", report_format: "pdf" });
  const sfreq = (patch) => setSchedule((s) => ({ ...s, freq: { ...s.freq, ...patch } }));
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  async function submit(e) {
    e.preventDefault();
    setErr("");
    let t;
    try { t = buildTarget(); }
    catch { return setErr("HTTP body/headers must be valid JSON"); }
    if (tools.custom && !tools.prompt_set_id) {
      return setErr("Select a prompt set for the Custom prompts engine, or turn it off.");
    }
    if (!tools.promptfoo && !tools.garak && !tools.pyrit && !tools.inspect && !tools.custom && !tools.deepteam) {
      return setErr("Enable at least one engine.");
    }
    const payload = { name, description: "", target: t, tools: { ...tools, purpose } };
    try {
      if (schedule.enabled) {
        await api.post("/api/schedules", {
          name, template: payload, freq: schedule.freq, enabled: true,
          report_emails: schedule.report_emails.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
          report_format: schedule.report_format,
        });
        nav("/schedules");
      } else {
        const r = await api.post("/api/campaigns", payload);
        nav(`/campaigns/${r.id}`);
      }
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
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-bold">2 · Target</h2>
          <div className="flex items-center gap-2">
            {savedTargets.length > 0 && (
              <select className="input w-auto py-1 text-sm" value={selectedSaved}
                      onChange={(e) => { setSelectedSaved(e.target.value); loadSavedTarget(e.target.value); }}>
                <option value="">Load saved target…</option>
                {savedTargets.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.type})</option>)}
              </select>
            )}
            <button type="button" className="btn-ghost py-1 text-sm" onClick={saveCurrentTarget}>Save this target</button>
          </div>
        </div>
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
              // Only Promptfoo can drive a browser UI
              if (tt.id === "browser") {
                setTools((t) => ({ ...t, promptfoo: true, garak: false, pyrit: false, inspect: false }));
              }
              setTestResult(null);
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
        ) : target.type === "browser" ? (
          <div className="grid sm:grid-cols-2 gap-4">
            <p className="sm:col-span-2 text-xs text-slate-500">
              For a model reachable only through a web chat window. A headless browser types each
              prompt and scrapes the reply. Set the DOM selectors to match your UI (right-click →
              Inspect). Only the Promptfoo stage runs for browser targets.
            </p>
            <div className="sm:col-span-2"><label className="label">Chat UI URL</label>
              <input className="input" value={browser.url} placeholder="https://your-app.example/chat"
                     onChange={(e) => setBrowser({ ...browser, url: e.target.value })} required /></div>
            <div><label className="label">Input selector</label>
              <input className="input font-mono text-xs" value={browser.input_selector}
                     onChange={(e) => setBrowser({ ...browser, input_selector: e.target.value })} /></div>
            <div><label className="label">Send button selector (blank = Enter)</label>
              <input className="input font-mono text-xs" value={browser.send_button_selector}
                     onChange={(e) => setBrowser({ ...browser, send_button_selector: e.target.value })} /></div>
            <div><label className="label">Assistant bubble selector</label>
              <input className="input font-mono text-xs" value={browser.response_bubble_selector}
                     onChange={(e) => setBrowser({ ...browser, response_bubble_selector: e.target.value })} /></div>
            <div><label className="label">Streaming indicator selector (optional)</label>
              <input className="input font-mono text-xs" value={browser.streaming_indicator_selector}
                     onChange={(e) => setBrowser({ ...browser, streaming_indicator_selector: e.target.value })} /></div>
            {/* ---- Saved authenticated session (recommended for SSO/MFA) ---- */}
            <div className="sm:col-span-2 border-t pt-3">
              <label className="label">Saved browser session (recommended for login)</label>
              <p className="text-xs text-slate-500 mb-2">
                Record a real, logged-in session on your machine and reuse it — handles SSO, MFA and
                anything you can do by hand. Run:
                <code className="block mt-1 bg-slate-100 px-2 py-1 rounded font-mono">npx playwright codegen --save-storage=auth.json {browser.url || "https://your-app/chat"}</code>
                log in, close the window, then upload <code>auth.json</code> here.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <select className="input w-auto" value={browser.session_id || ""}
                        onChange={(e) => setBrowser({ ...browser, session_id: e.target.value ? +e.target.value : null })}>
                  <option value="">No saved session</option>
                  {sessions.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                <label className="btn-ghost cursor-pointer">
                  Upload session…
                  <input type="file" accept=".json" className="hidden"
                         onChange={(e) => e.target.files[0] && uploadSession(e.target.files[0])} />
                </label>
                {sessMsg && <span className="text-xs text-slate-600">{sessMsg}</span>}
              </div>
            </div>

            {/* ---- Login macro (Burp-style recorded login) ---- */}
            <div className="sm:col-span-2 border-t pt-3">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" checked={needsLogin}
                       onChange={(e) => { setNeedsLogin(e.target.checked); if (e.target.checked && browser.setup_steps.length === 0) addStep(); }} />
                This chat UI requires login (record a login sequence)
              </label>
              {needsLogin && (
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-slate-500">
                    Steps run once to log in; every prompt then reuses the session. Use
                    <code className="mx-1">{"{{secret.NAME}}"}</code>for passwords and set <code>NAME</code> as an
                    environment variable on the backend — secrets are never stored.
                  </p>
                  {browser.setup_steps.map((s, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2 bg-white rounded border border-slate-200 p-2">
                      <span className="text-xs text-slate-400 w-4">{i + 1}</span>
                      <select className="input w-auto py-1" value={s.action} onChange={(e) => setStep(i, { action: e.target.value })}>
                        {STEP_ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
                      </select>
                      {["goto", "waitForURL"].includes(s.action) && (
                        <input className="input flex-1 min-w-[180px] py-1 font-mono text-xs" placeholder="https://app/login"
                               value={s.url} onChange={(e) => setStep(i, { url: e.target.value })} />
                      )}
                      {["fill", "type", "click", "press", "waitForSelector"].includes(s.action) && (
                        <input className="input flex-1 min-w-[160px] py-1 font-mono text-xs" placeholder="CSS selector, e.g. #email"
                               value={s.selector} onChange={(e) => setStep(i, { selector: e.target.value })} />
                      )}
                      {["fill", "type", "press"].includes(s.action) && (
                        <input className="input flex-1 min-w-[140px] py-1 font-mono text-xs"
                               placeholder={s.action === "press" ? "key (e.g. Enter)" : "value or {{secret.CHAT_PASS}}"}
                               value={s.value} onChange={(e) => setStep(i, { value: e.target.value })} />
                      )}
                      {s.action === "sleep" && (
                        <input className="input w-28 py-1" type="number" placeholder="ms" value={s.ms || ""}
                               onChange={(e) => setStep(i, { ms: +e.target.value })} />
                      )}
                      <button type="button" className="text-red-500 text-xs" onClick={() => delStep(i)}>remove</button>
                    </div>
                  ))}
                  <button type="button" className="btn-ghost py-1 text-xs" onClick={addStep}>+ Add step</button>
                  <div className="pt-1">
                    <label className="label">New-chat selector (optional — reset the conversation per prompt)</label>
                    <input className="input font-mono text-xs" value={browser.new_chat_selector}
                           placeholder="button[aria-label='New chat']"
                           onChange={(e) => setBrowser({ ...browser, new_chat_selector: e.target.value })} />
                  </div>
                </div>
              )}
            </div>

            <div className="sm:col-span-2 flex items-center gap-3">
              <button type="button" className="btn-ghost" onClick={testConnection} disabled={testing || !browser.url}>
                {testing ? "Testing…" : "Test connection"}
              </button>
              <span className="text-xs text-slate-500">Drives the chat UI once (runs the login macro first); can take ~10–30s.</span>
            </div>
            {testResult && (
              <div className={`sm:col-span-2 rounded-lg px-3 py-2 text-sm ${testResult.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"}`}>
                <div className="font-semibold">{testResult.ok ? "✓ Scraped a reply" : "✗ Test failed"}</div>
                {testResult.reply && <div className="mt-1">Reply: <span className="font-mono">{testResult.reply}</span></div>}
                {testResult.error && <div className="mt-1">{testResult.error}</div>}
              </div>
            )}
          </div>
        ) : target.type === "mcp" ? (
          <div className="grid sm:grid-cols-2 gap-4">
            <p className="sm:col-span-2 text-xs text-slate-500">
              Test an LLM agent wired to MCP tools. The base model calls the MCP server(s) below; red-team
              plugins (excessive agency, tool misuse, injection via tool results) probe how it uses them.
              Use the <b>Agentic &amp; RAG</b> template in Tools.
            </p>
            <div><label className="label">Base model provider</label>
              <select className="input" value={mcp.base_provider} onChange={(e) => setMcp({ ...mcp, base_provider: e.target.value })}>
                {["openai", "anthropic", "google", "azure", "ollama", "bedrock"].map((p) => <option key={p} value={p}>{p}</option>)}
              </select></div>
            <div><label className="label">Model</label>
              <input className="input" value={target.model} placeholder="gpt-4.1-mini"
                     onChange={(e) => setTarget({ ...target, model: e.target.value })} required /></div>
            <div className="sm:col-span-2">
              <label className="label">MCP servers (HTTP/SSE)</label>
              {mcp.servers.map((sv, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 mb-2">
                  <input className="input flex-1 min-w-[220px] font-mono text-xs" placeholder="https://mcp.example.com/sse"
                         value={sv.url} onChange={(e) => setMcp({ ...mcp, servers: mcp.servers.map((s, j) => j === i ? { ...s, url: e.target.value } : s) })} />
                  <input className="input flex-1 min-w-[180px] font-mono text-xs" placeholder='Headers JSON (optional) {"Authorization":"Bearer ..."}'
                         value={sv.headers} onChange={(e) => setMcp({ ...mcp, servers: mcp.servers.map((s, j) => j === i ? { ...s, headers: e.target.value } : s) })} />
                  {mcp.servers.length > 1 && <button type="button" className="text-red-500 text-xs"
                    onClick={() => setMcp({ ...mcp, servers: mcp.servers.filter((_, j) => j !== i) })}>remove</button>}
                </div>
              ))}
              <button type="button" className="btn-ghost py-1 text-xs"
                onClick={() => setMcp({ ...mcp, servers: [...mcp.servers, { url: "", headers: "" }] })}>+ Add server</button>
            </div>
            <div className="sm:col-span-2"><label className="label">System prompt (optional)</label>
              <textarea className="input" rows={2} value={target.system_prompt}
                        onChange={(e) => setTarget({ ...target, system_prompt: e.target.value })} /></div>
            <div className="sm:col-span-2 flex items-center gap-3">
              <button type="button" className="btn-ghost" onClick={testConnection} disabled={testing || !target.model}>
                {testing ? "Testing…" : "Test connection"}
              </button>
              {testResult && (
                <span className={`text-sm ${testResult.ok ? "text-green-700" : "text-red-700"}`}>
                  {testResult.ok ? "✓ " : "✗ "}{testResult.message || testResult.error}
                </span>
              )}
            </div>
          </div>
        ) : target.type !== "http" ? (
          <div className="grid sm:grid-cols-2 gap-4">
            <div><label className="label">Model</label>
              <input className="input" value={target.model} onChange={(e) => setTarget({ ...target, model: e.target.value })} required /></div>
            {(["openai", "ollama", "azure", "google"].includes(target.type)) && (
              <div><label className="label">Base URL (optional)</label>
                <input className="input" value={target.base_url} placeholder={target.type === "ollama" ? "http://host:11434" : target.type === "azure" ? "your-resource.openai.azure.com" : "base URL (optional)"}
                       onChange={(e) => setTarget({ ...target, base_url: e.target.value })} /></div>
            )}
            <div className="sm:col-span-2"><label className="label">System prompt (optional)</label>
              <textarea className="input" rows={2} value={target.system_prompt}
                        onChange={(e) => setTarget({ ...target, system_prompt: e.target.value })} /></div>
          </div>
        ) : (
          <div className="grid sm:grid-cols-6 gap-4">
            <div className="sm:col-span-6 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <label className="label">Paste a curl command to auto-fill (optional)</label>
              <textarea className="input font-mono text-xs" rows={3} value={curlText}
                        placeholder={"curl https://your-app/chat -H 'Authorization: Bearer sk-...' \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"message\":\"hello\"}'"}
                        onChange={(e) => setCurlText(e.target.value)} />
              <div className="mt-2 flex items-center gap-3">
                <button type="button" className="btn-ghost" onClick={applyCurl} disabled={!curlText.trim()}>Parse curl</button>
                {curlMsg && <span className="text-xs text-slate-600">{curlMsg}</span>}
              </div>
            </div>
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
            {testResult && (() => {
              const almost = !testResult.ok && testResult.suggested_paths?.length > 0;
              const tone = testResult.ok ? "bg-green-50 text-green-800"
                : almost ? "bg-amber-50 text-amber-800" : "bg-red-50 text-red-700";
              return (
              <div className={`sm:col-span-6 rounded-lg px-3 py-2 text-sm ${tone}`}>
                <div className="font-semibold">
                  {testResult.ok ? "✓ Connection OK"
                    : almost ? "✓ Reached the endpoint — now pick the reply field"
                      : "✗ Test failed"}
                  {testResult.status ? ` (HTTP ${testResult.status})` : ""}
                </div>
                {testResult.reply && <div className="mt-1">Extracted reply: <span className="font-mono">{testResult.reply}</span></div>}
                {testResult.error && <div className="mt-1">{testResult.error}</div>}
                {testResult.extract_error && <div className="mt-1">{testResult.extract_error}</div>}
                {testResult.suggested_paths?.length > 0 && (
                  <div className="mt-2">
                    <div className="text-xs font-medium">Response path — click to use:</div>
                    <div className="mt-1 flex flex-col gap-1">
                      {testResult.suggested_paths.map((s) => (
                        <button type="button" key={s.path}
                          className="text-left text-xs rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50"
                          onClick={() => { setHttp((prev) => ({ ...prev, response_path: s.path })); setTimeout(testConnection, 0); }}>
                          <span className="font-mono text-slate-800">{s.path}</span>
                          <span className="text-slate-500"> — “{s.preview}”</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {testResult.tls_note && <div className="mt-1 text-amber-700">{testResult.tls_note}</div>}
                {testResult.raw && !testResult.reply && (
                  <details className="mt-1"><summary className="cursor-pointer">Raw response</summary>
                    <pre className="mt-1 bg-white/60 p-2 rounded overflow-auto max-h-40 whitespace-pre-wrap text-xs">{testResult.raw}</pre></details>
                )}
              </div>
              ); })()}
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
          <Toggle on={tools.custom} set={(v) => up({ custom: v })} label="Custom prompts" desc="Your own prompts/datasets, graded your way" />
          <Toggle on={tools.deepteam} set={(v) => up({ deepteam: v })} label="DeepTeam" desc="confident-ai: agentic vulns + attack simulation" />
        </div>

        {tools.promptfoo && (
          <div className="border-t pt-4 space-y-3">
            <div className="font-semibold text-sm">Templates - one-click plugin sets</div>
            <div className="flex flex-wrap gap-2">
              {(catalog.promptfoo.presets || []).map((pr) => (
                <button type="button" key={pr.id} title={pr.desc}
                  className="chip border bg-white border-slate-300 hover:bg-violet-50"
                  onClick={() => up({ promptfoo: true, promptfoo_plugins: pr.plugins })}>
                  {pr.label} <span className="text-slate-400">({pr.plugins.length})</span>
                </button>
              ))}
            </div>
            <div className="font-semibold text-sm pt-2">Promptfoo plugins</div>
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
            {tools.promptfoo_plugins.includes("indirect-prompt-injection") && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 mt-2">
                <label className="label">RAG injection variable</label>
                <input className="input w-48 font-mono text-xs" value={tools.indirect_var}
                       onChange={(e) => up({ indirect_var: e.target.value })} placeholder="context" />
                <p className="text-xs text-amber-700 mt-1">
                  Name of the field that carries untrusted retrieved content. For an HTTP target, include
                  <code className="mx-1">{"{{" + (tools.indirect_var || "context") + "}}"}</code>in the request body where documents are inserted.
                </p>
              </div>
            )}
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
        {tools.custom && (
          <div className="border-t pt-4 space-y-2">
            <div className="font-semibold text-sm">Custom prompt set</div>
            {promptSets.length === 0 ? (
              <p className="text-xs text-slate-500">
                No saved prompt sets yet. Create one under <a className="underline" href="/prompts">Prompts &amp; Datasets</a>,
                then come back and select it here.
              </p>
            ) : (
              <>
                <select className="input" value={tools.prompt_set_id || ""}
                        onChange={(e) => up({ prompt_set_id: e.target.value ? +e.target.value : null })}>
                  <option value="">Select a prompt set…</option>
                  {promptSets.map((s) => (
                    <option key={s.id} value={s.id}>{s.name} ({s.count} prompts · {s.grading?.severity || "high"})</option>
                  ))}
                </select>
                <p className="text-xs text-slate-500">
                  Runs your prompts against the target and grades each reply with the set's rubric / keyword rules.
                  Works with every target type, including the web chat UI. Manage sets under{" "}
                  <a className="underline" href="/prompts">Prompts &amp; Datasets</a>.
                </p>
              </>
            )}
          </div>
        )}

        {tools.deepteam && (
          <div className="border-t pt-4 space-y-3">
            <div className="font-semibold text-sm">DeepTeam vulnerabilities</div>
            <p className="text-xs text-amber-600">
              DeepTeam simulates attacks with an LLM — set <code>XYBERAH_GRADER</code>/<code>OPENAI_API_KEY</code>.
              Works with HTTP &amp; demo targets.
            </p>
            {(catalog.deepteam?.vulnerabilities || []).length > 0 && (
              <CheckGroup options={catalog.deepteam.vulnerabilities} selected={tools.deepteam_vulnerabilities}
                onChange={(v) => up({ deepteam_vulnerabilities: v })} />
            )}
            <div className="text-xs text-slate-500">Attacks</div>
            <CheckGroup options={catalog.deepteam?.attacks || []} selected={tools.deepteam_attacks}
              onChange={(v) => up({ deepteam_attacks: v })} />
            <div className="w-56"><label className="label">Attacks per vulnerability</label>
              <input type="number" min="1" max="10" className="input" value={tools.deepteam_attacks_per_vuln}
                     onChange={(e) => up({ deepteam_attacks_per_vuln: +e.target.value })} /></div>
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

      <section className="card p-5 space-y-3">
        <Toggle on={schedule.enabled} set={(v) => setSchedule({ ...schedule, enabled: v })}
          label="Run on a schedule" desc="Re-run this scan automatically to catch model drift and regressions" />
        {schedule.enabled && (
          <div className="flex flex-wrap items-end gap-3 border-t pt-3">
            <div><label className="label">Frequency</label>
              <select className="input w-auto" value={schedule.freq.kind} onChange={(e) => sfreq({ kind: e.target.value })}>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="interval">Every N hours</option>
              </select></div>
            {schedule.freq.kind === "interval" ? (
              <div><label className="label">Hours between runs</label>
                <input type="number" min="1" className="input w-28"
                       value={Math.round((schedule.freq.minutes || 1440) / 60)}
                       onChange={(e) => sfreq({ minutes: Math.max(1, +e.target.value) * 60 })} /></div>
            ) : (
              <>
                {schedule.freq.kind === "weekly" && (
                  <div><label className="label">Day</label>
                    <select className="input w-auto" value={schedule.freq.day} onChange={(e) => sfreq({ day: +e.target.value })}>
                      {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                    </select></div>
                )}
                <div><label className="label">Time (UTC)</label>
                  <input type="time" className="input w-32" value={schedule.freq.at}
                         onChange={(e) => sfreq({ at: e.target.value })} /></div>
              </>
            )}
            <div className="w-full border-t pt-3">
              <label className="label">Email report after each run (optional)</label>
              <div className="flex flex-wrap items-start gap-2">
                <textarea className="input flex-1 min-w-[240px] text-sm" rows={2}
                          value={schedule.report_emails}
                          onChange={(e) => setSchedule({ ...schedule, report_emails: e.target.value })}
                          placeholder="security@acme.com, ciso@acme.com" />
                <select className="input w-auto" value={schedule.report_format}
                        onChange={(e) => setSchedule({ ...schedule, report_format: e.target.value })}>
                  <option value="pdf">PDF report</option>
                  <option value="attestation">Signed attestation</option>
                </select>
              </div>
              <p className="text-xs text-slate-500 mt-1">Comma or newline separated. Requires SMTP configured in Settings.</p>
            </div>
            <p className="text-xs text-slate-500 w-full">Manage recurring scans under <a className="underline" href="/schedules">Schedules</a>.</p>
          </div>
        )}
      </section>

      <div className="flex gap-3">
        <button className="btn-primary">{schedule.enabled ? "Create schedule" : "Create campaign"}</button>
        <button type="button" className="btn-ghost" onClick={() => nav("/")}>Cancel</button>
      </div>
    </form>
  );
}
