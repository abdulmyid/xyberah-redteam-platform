import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useApp } from "../../lib/context.jsx";

export default function Branding() {
  const { refreshBranding } = useApp();
  const [b, setB] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => { api.get("/api/branding/me").then(setB); }, []);
  if (!b) return <p className="text-slate-500">Loading…</p>;
  const set = (k, v) => setB({ ...b, [k]: v });

  async function save() {
    setMsg("");
    try { await api.put("/api/branding", b); await refreshBranding(); setMsg("Saved."); }
    catch (e) { setMsg(e.message); }
  }

  async function uploadLogo(slot, file) {
    const fd = new FormData(); fd.append("file", file);
    const r = await api.upload(`/api/branding/logo?slot=${slot}`, fd);
    set(slot, r.url); await refreshBranding();
  }

  return (
    <div className="card p-6 space-y-5 max-w-2xl">
      <h2 className="font-bold text-lg">White-label branding</h2>
      <p className="text-sm text-slate-500">Applies to everyone in your company.</p>

      <div className="grid sm:grid-cols-2 gap-4">
        <div><label className="label">Application name</label>
          <input className="input" value={b.app_name} onChange={(e) => set("app_name", e.target.value)} /></div>
        <div><label className="label">Tagline</label>
          <input className="input" value={b.tagline} onChange={(e) => set("tagline", e.target.value)} /></div>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        {["primary", "secondary", "accent"].map((k) => (
          <div key={k}><label className="label capitalize">{k} color</label>
            <div className="flex items-center gap-2">
              <input type="color" value={b[k]} onChange={(e) => set(k, e.target.value)} className="h-9 w-12 rounded border" />
              <input className="input" value={b[k]} onChange={(e) => set(k, e.target.value)} />
            </div></div>
        ))}
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        {[["logo_light", "Logo (light bg)"], ["logo_dark", "Logo (dark bg)"], ["favicon", "Favicon"]].map(([slot, label]) => (
          <div key={slot}>
            <label className="label">{label}</label>
            {b[slot] && <img src={b[slot]} alt="" className="h-8 mb-2" onError={(e) => (e.target.style.display = "none")} />}
            <input type="file" accept=".svg,.png,.jpg,.jpeg,.webp"
                   onChange={(e) => e.target.files[0] && uploadLogo(slot, e.target.files[0])} className="text-xs" />
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <input type="checkbox" checked={b.hide_footer} onChange={(e) => set("hide_footer", e.target.checked)} id="hf" />
        <label htmlFor="hf" className="text-sm">Hide the open-source footer</label>
      </div>
      <div><label className="label">Footer text</label>
        <input className="input" value={b.footer_text} onChange={(e) => set("footer_text", e.target.value)} /></div>
      <div><label className="label">Support URL</label>
        <input className="input" value={b.support_url} onChange={(e) => set("support_url", e.target.value)} /></div>

      <div className="flex items-center gap-3">
        <button className="btn-primary" onClick={save}>Save branding</button>
        {msg && <span className="text-sm text-slate-500">{msg}</span>}
      </div>
    </div>
  );
}
