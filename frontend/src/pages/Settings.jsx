import { useState } from "react";
import { atLeast } from "../lib/api";
import { useApp } from "../lib/context.jsx";
import Branding from "./settings/Branding.jsx";
import Security from "./settings/Security.jsx";
import Users from "./settings/Users.jsx";
import Companies from "./settings/Companies.jsx";
import Email from "./settings/Email.jsx";
import Tls from "./settings/Tls.jsx";
import Tools from "./settings/Tools.jsx";
import Audit from "./settings/Audit.jsx";

export default function Settings() {
  const { user } = useApp();
  const tabs = [
    { id: "branding", label: "Branding", show: atLeast(user.role, "company_admin"), el: <Branding /> },
    { id: "security", label: "My security (2FA)", show: true, el: <Security /> },
    { id: "users", label: "Users & invites", show: atLeast(user.role, "company_admin"), el: <Users /> },
    { id: "companies", label: "Companies", show: user.role === "global_admin", el: <Companies /> },
    { id: "email", label: "Email (SMTP)", show: user.role === "global_admin", el: <Email /> },
    { id: "tls", label: "TLS certificate", show: user.role === "global_admin", el: <Tls /> },
    { id: "tools", label: "Scanners", show: true, el: <Tools /> },
    { id: "audit", label: "Audit log", show: atLeast(user.role, "company_admin"), el: <Audit /> },
  ].filter((t) => t.show);
  const [active, setActive] = useState(tabs[0].id);

  return (
    <div>
      <h1 className="text-2xl font-extrabold mb-5">Settings</h1>
      <div className="flex gap-6">
        <aside className="w-52 shrink-0 space-y-1">
          {tabs.map((t) => (
            <button key={t.id} onClick={() => setActive(t.id)}
              className={`tab block w-full text-left ${active === t.id ? "tab-active" : "hover:bg-slate-100"}`}>
              {t.label}
            </button>
          ))}
        </aside>
        <div className="flex-1 min-w-0">{tabs.find((t) => t.id === active)?.el}</div>
      </div>
    </div>
  );
}
