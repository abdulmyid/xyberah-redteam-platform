import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function Companies() {
  const [companies, setCompanies] = useState([]);
  const [form, setForm] = useState({ name: "", max_users: 25, max_concurrent_campaigns: 1 });
  const [msg, setMsg] = useState("");

  const load = () => api.get("/api/companies").then(setCompanies);
  useEffect(() => { load(); }, []);

  async function create(e) {
    e.preventDefault(); setMsg("");
    try { await api.post("/api/companies", form); setForm({ name: "", max_users: 25, max_concurrent_campaigns: 1 }); load(); }
    catch (e) { setMsg(e.message); }
  }
  const toggle = (id, disabled) => api.post(`/api/companies/${id}/disable?disabled=${disabled}`).then(load);

  return (
    <div className="space-y-5 max-w-3xl">
      <form onSubmit={create} className="card p-5 space-y-3">
        <h2 className="font-bold text-lg">Create a company</h2>
        {msg && <div className="rounded bg-red-50 text-red-700 text-sm px-3 py-2">{msg}</div>}
        <div className="flex flex-wrap gap-2">
          <input className="input flex-1 min-w-[200px]" placeholder="Company name" required
                 value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="input w-28" type="number" min="1" title="Max users"
                 value={form.max_users} onChange={(e) => setForm({ ...form, max_users: +e.target.value })} />
          <input className="input w-36" type="number" min="1" title="Max concurrent campaigns"
                 value={form.max_concurrent_campaigns} onChange={(e) => setForm({ ...form, max_concurrent_campaigns: +e.target.value })} />
          <button className="btn-primary">Create</button>
        </div>
        <p className="text-xs text-slate-500">Then invite a Company admin for it under “Users & invites”.</p>
      </form>

      <div className="card p-5">
        <table className="w-full text-sm">
          <thead className="text-slate-500 text-left"><tr><th className="p-2">Company</th><th className="p-2">Users</th><th className="p-2">Limits</th><th className="p-2"></th></tr></thead>
          <tbody>
            {companies.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="p-2"><div className="font-medium">{c.name}</div><div className="text-xs text-slate-500">{c.slug}{c.disabled && " · disabled"}</div></td>
                <td className="p-2">{c.users}/{c.max_users}</td>
                <td className="p-2 text-xs">{c.max_concurrent_campaigns} concurrent</td>
                <td className="p-2 text-right"><button className="text-xs text-slate-600" onClick={() => toggle(c.id, !c.disabled)}>{c.disabled ? "Enable" : "Disable"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
