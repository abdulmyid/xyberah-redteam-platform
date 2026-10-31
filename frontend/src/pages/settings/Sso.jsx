import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const ROLES = ["viewer", "analyst", "company_admin"];

export default function Sso() {
  const [cfg, setCfg] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [domains, setDomains] = useState([]);
  const [tokens, setTokens] = useState([]);
  const [newDomain, setNewDomain] = useState({ domain: "", company_id: "", default_role: "viewer" });
  const [newToken, setNewToken] = useState({ name: "", company_id: "", default_role: "viewer" });
  const [createdToken, setCreatedToken] = useState(null);
  const [msg, setMsg] = useState("");

  const loadAll = () => {
    api.get("/api/sso/config").then((c) => setCfg({ ...c, oidc_client_secret: "" }));
    api.get("/api/companies").then(setCompanies).catch(() => {});
    api.get("/api/sso/domains").then(setDomains).catch(() => {});
    api.get("/api/sso/scim-tokens").then(setTokens).catch(() => {});
  };
  useEffect(() => { loadAll(); }, []);

  const set = (patch) => setCfg((c) => ({ ...c, ...patch }));
  const companyName = (id) => companies.find((c) => c.id === id)?.name || `#${id}`;

  async function saveCfg() {
    setMsg("");
    try {
      await api.put("/api/sso/config", {
        oidc_enabled: cfg.oidc_enabled, oidc_issuer: cfg.oidc_issuer, oidc_client_id: cfg.oidc_client_id,
        oidc_client_secret: cfg.oidc_client_secret || "", oidc_scopes: cfg.oidc_scopes,
        saml_enabled: cfg.saml_enabled, saml_idp_entity_id: cfg.saml_idp_entity_id,
        saml_idp_sso_url: cfg.saml_idp_sso_url, saml_idp_x509: cfg.saml_idp_x509,
        sp_base_url: cfg.sp_base_url, default_role: cfg.default_role, auto_provision: cfg.auto_provision,
      });
      setMsg("Saved ✓"); loadAll();
    } catch (e) { setMsg(e.message); }
  }
  async function addDomain() {
    if (!newDomain.domain || !newDomain.company_id) return setMsg("Domain and company required.");
    await api.post("/api/sso/domains", { ...newDomain, company_id: +newDomain.company_id });
    setNewDomain({ domain: "", company_id: "", default_role: "viewer" }); loadAll();
  }
  async function delDomain(id) { await api.del(`/api/sso/domains/${id}`); loadAll(); }
  async function addToken() {
    if (!newToken.company_id) return setMsg("Pick a company for the SCIM token.");
    const r = await api.post("/api/sso/scim-tokens", { ...newToken, company_id: +newToken.company_id });
    setCreatedToken(r); setNewToken({ name: "", company_id: "", default_role: "viewer" }); loadAll();
  }
  async function revokeToken(id) { if (confirm("Revoke this SCIM token?")) { await api.del(`/api/sso/scim-tokens/${id}`); loadAll(); } }

  if (!cfg) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="font-bold text-lg">Single sign-on (SSO)</h2>
        <p className="text-sm text-slate-500">OIDC & SAML login with domain-based provisioning and SCIM sync.</p>
      </div>

      <div className="card p-5 space-y-3">
        <label className="label">Public base URL of this app</label>
        <input className="input" value={cfg.sp_base_url} onChange={(e) => set({ sp_base_url: e.target.value })}
               placeholder="https://xyberah.yourco.com:8443" />
        <p className="text-xs text-slate-500">Used to build OIDC redirect URI and SAML ACS/metadata URLs.</p>
        <div className="flex gap-4">
          <div><label className="label">Default role (new users)</label>
            <select className="input" value={cfg.default_role} onChange={(e) => set({ default_role: e.target.value })}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select></div>
          <label className="flex items-center gap-2 text-sm mt-6">
            <input type="checkbox" checked={cfg.auto_provision} onChange={(e) => set({ auto_provision: e.target.checked })} />
            Auto-create users on first SSO login (JIT)
          </label>
        </div>
      </div>

      {/* OIDC */}
      <div className="card p-5 space-y-3">
        <label className="flex items-center gap-2 font-semibold">
          <input type="checkbox" checked={cfg.oidc_enabled} onChange={(e) => set({ oidc_enabled: e.target.checked })} />
          OIDC
        </label>
        <div><label className="label">Issuer URL</label>
          <input className="input" value={cfg.oidc_issuer} onChange={(e) => set({ oidc_issuer: e.target.value })}
                 placeholder="https://your-tenant.okta.com/oauth2/default" /></div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label">Client ID</label>
            <input className="input" value={cfg.oidc_client_id} onChange={(e) => set({ oidc_client_id: e.target.value })} /></div>
          <div><label className="label">Client secret {cfg.oidc_secret_set && <span className="text-xs text-green-600">(set — blank keeps it)</span>}</label>
            <input className="input" type="password" value={cfg.oidc_client_secret}
                   onChange={(e) => set({ oidc_client_secret: e.target.value })} placeholder="••••••••" /></div>
        </div>
        <div><label className="label">Scopes</label>
          <input className="input" value={cfg.oidc_scopes} onChange={(e) => set({ oidc_scopes: e.target.value })} /></div>
        <p className="text-xs text-slate-500">Redirect URI: <code>{(cfg.sp_base_url || "<base>")}/api/auth/oidc/callback</code></p>
      </div>

      {/* SAML */}
      <div className="card p-5 space-y-3">
        <label className="flex items-center gap-2 font-semibold">
          <input type="checkbox" checked={cfg.saml_enabled} onChange={(e) => set({ saml_enabled: e.target.checked })} />
          SAML 2.0
        </label>
        <div><label className="label">IdP entity ID</label>
          <input className="input" value={cfg.saml_idp_entity_id} onChange={(e) => set({ saml_idp_entity_id: e.target.value })} /></div>
        <div><label className="label">IdP SSO URL</label>
          <input className="input" value={cfg.saml_idp_sso_url} onChange={(e) => set({ saml_idp_sso_url: e.target.value })} /></div>
        <div><label className="label">IdP x509 certificate</label>
          <textarea className="input font-mono text-xs" rows={3} value={cfg.saml_idp_x509}
                    onChange={(e) => set({ saml_idp_x509: e.target.value })} placeholder="MIIC..." /></div>
        <p className="text-xs text-slate-500">
          ACS: <code>{(cfg.sp_base_url || "<base>")}/api/auth/saml/acs</code> ·
          Metadata: <code>{(cfg.sp_base_url || "<base>")}/api/auth/saml/metadata</code>
        </p>
      </div>

      <div className="flex items-center gap-3">
        <button className="btn-primary" onClick={saveCfg}>Save SSO settings</button>
        {msg && <span className="text-sm text-slate-600">{msg}</span>}
      </div>

      {/* Domain maps */}
      <div className="card p-5 space-y-3">
        <div className="font-semibold text-sm">Domain → company mapping</div>
        <p className="text-xs text-slate-500">A new SSO user is placed in the company mapped to their email domain.</p>
        {domains.map((d) => (
          <div key={d.id} className="flex items-center gap-2 text-sm">
            <code className="flex-1">@{d.domain}</code>
            <span>→ {companyName(d.company_id)} ({d.default_role})</span>
            <button className="btn-ghost py-1 text-xs text-red-500" onClick={() => delDomain(d.id)}>remove</button>
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-2">
          <input className="input w-40" placeholder="acme.com" value={newDomain.domain}
                 onChange={(e) => setNewDomain({ ...newDomain, domain: e.target.value })} />
          <select className="input w-auto" value={newDomain.company_id}
                  onChange={(e) => setNewDomain({ ...newDomain, company_id: e.target.value })}>
            <option value="">Company…</option>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="input w-auto" value={newDomain.default_role}
                  onChange={(e) => setNewDomain({ ...newDomain, default_role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button className="btn-ghost" onClick={addDomain}>Add</button>
        </div>
      </div>

      {/* SCIM */}
      <div className="card p-5 space-y-3">
        <div className="font-semibold text-sm">SCIM provisioning tokens</div>
        <p className="text-xs text-slate-500">Give your IdP this token to create/deactivate users in a company. Base URL: <code>{(cfg.sp_base_url || "<base>")}/scim/v2</code></p>
        {createdToken && (
          <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs">
            <div className="font-semibold">Copy this token now — it is shown once:</div>
            <code className="block mt-1 break-all">{createdToken.token}</code>
          </div>
        )}
        {tokens.map((t) => (
          <div key={t.id} className="flex items-center gap-2 text-sm">
            <span className="flex-1">{t.name} → {companyName(t.company_id)} ({t.default_role})</span>
            <button className="btn-ghost py-1 text-xs text-red-500" onClick={() => revokeToken(t.id)}>revoke</button>
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-2">
          <input className="input w-40" placeholder="Okta SCIM" value={newToken.name}
                 onChange={(e) => setNewToken({ ...newToken, name: e.target.value })} />
          <select className="input w-auto" value={newToken.company_id}
                  onChange={(e) => setNewToken({ ...newToken, company_id: e.target.value })}>
            <option value="">Company…</option>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="input w-auto" value={newToken.default_role}
                  onChange={(e) => setNewToken({ ...newToken, default_role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button className="btn-ghost" onClick={addToken}>Create token</button>
        </div>
      </div>
    </div>
  );
}
