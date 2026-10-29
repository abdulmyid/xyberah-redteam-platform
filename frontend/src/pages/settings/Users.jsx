import { useEffect, useState } from "react";
import { api, ROLES } from "../../lib/api";
import { useApp } from "../../lib/context.jsx";

export default function Users() {
  const { user } = useApp();
  const [users, setUsers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [form, setForm] = useState({ email: "", role: "viewer", company_id: user.company_id || "" });
  const [msg, setMsg] = useState("");

  const load = () => {
    api.get("/api/users").then(setUsers);
    api.get("/api/invites").then(setInvites);
    if (user.role === "global_admin") api.get("/api/companies").then(setCompanies);
  };
  useEffect(() => { load(); }, []);

  const roleOptions = Object.entries(ROLES).filter(([r]) =>
    user.role === "global_admin" ? true : ["viewer", "analyst", "company_admin"].includes(r));

  async function invite(e) {
    e.preventDefault(); setMsg("");
    try {
      const body = { email: form.email, role: form.role };
      if (user.role === "global_admin") body.company_id = form.company_id ? +form.company_id : null;
      const r = await api.post("/api/invites", body);
      setMsg(r.delivery?.delivered === "smtp" ? "Invitation emailed." : `Invite link: ${r.invite_url}`);
      setForm({ ...form, email: "" }); load();
    } catch (e) { setMsg(e.message); }
  }

  const setRole = (id, role) => api.patch(`/api/users/${id}/role`, { role }).then(load).catch((e) => alert(e.message));
  const disable = (id, d) => api.post(`/api/users/${id}/disable?disabled=${d}`).then(load).catch((e) => alert(e.message));
  const revoke = (id) => api.del(`/api/invites/${id}`).then(load);

  return (
    <div className="space-y-5 max-w-3xl">
      <form onSubmit={invite} className="card p-5 space-y-3">
        <h2 className="font-bold text-lg">Invite a user</h2>
        {msg && <div className="rounded bg-slate-100 text-sm px-3 py-2 break-all">{msg}</div>}
        <div className="flex flex-wrap gap-2">
          <input className="input flex-1 min-w-[200px]" type="email" placeholder="email@company.com" required
                 value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <select className="input w-auto" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {roleOptions.map(([r, l]) => <option key={r} value={r}>{l}</option>)}
          </select>
          {user.role === "global_admin" && (
            <select className="input w-auto" value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })}>
              <option value="">(no company)</option>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <button className="btn-primary">Send invite</button>
        </div>
      </form>

      {invites.length > 0 && (
        <div className="card p-5">
          <h3 className="font-bold mb-2">Pending invites</h3>
          <table className="w-full text-sm">
            <tbody>
              {invites.map((i) => (
                <tr key={i.id} className="border-t">
                  <td className="p-2">{i.email}</td><td className="p-2">{ROLES[i.role]}</td>
                  <td className="p-2 text-right"><button className="text-red-600 text-xs" onClick={() => revoke(i.id)}>Revoke</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card p-5">
        <h3 className="font-bold mb-2">Users</h3>
        <table className="w-full text-sm">
          <thead className="text-slate-500 text-left"><tr><th className="p-2">User</th><th className="p-2">Role</th><th className="p-2">2FA</th><th className="p-2"></th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t">
                <td className="p-2">
                  <div className="font-medium">{u.username}</div>
                  <div className="text-xs text-slate-500">{u.email}{u.disabled && " · disabled"}</div>
                </td>
                <td className="p-2">
                  {u.id === user.id ? ROLES[u.role] : (
                    <select className="input w-auto py-1" value={u.role} onChange={(e) => setRole(u.id, e.target.value)}>
                      {roleOptions.map(([r, l]) => <option key={r} value={r}>{l}</option>)}
                    </select>
                  )}
                </td>
                <td className="p-2">{u.totp_enabled ? <span className="chip sev-low">on</span> : <span className="text-slate-400 text-xs">off</span>}</td>
                <td className="p-2 text-right">
                  {u.id !== user.id && (
                    <button className="text-xs text-slate-600" onClick={() => disable(u.id, !u.disabled)}>
                      {u.disabled ? "Enable" : "Disable"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
