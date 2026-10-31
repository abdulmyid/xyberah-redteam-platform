import { Link, useLocation, useNavigate } from "react-router-dom";
import { useApp } from "../lib/context.jsx";
import { ROLES } from "../lib/api";

export default function Layout({ children }) {
  const { user, branding, logout } = useApp();
  const loc = useLocation();
  const nav = useNavigate();
  const b = branding || {};
  const link = (to, label) => {
    const active = loc.pathname === to || (to !== "/" && loc.pathname.startsWith(to));
    return (
      <Link
        to={to}
        className={`px-3 py-2 rounded-lg text-sm font-medium ${
          active ? "bg-violet-50" : "hover:bg-slate-100"
        }`}
        style={active ? { color: "var(--brand-primary)" } : {}}
      >
        {label}
      </Link>
    );
  };

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-6xl mx-auto px-5 h-14 flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2 font-extrabold text-lg">
            {b.logo_light ? (
              <img src={b.logo_light} alt={b.app_name} className="h-7" onError={(e) => (e.target.style.display = "none")} />
            ) : null}
            <span>{b.app_name || "Xyberah"}</span>
          </Link>
          <nav className="flex items-center gap-1 ml-4">
            {link("/", "Dashboard")}
            {link("/console", "Console")}
            {link("/prompts", "Prompts")}
            {link("/schedules", "Schedules")}
            {link("/model-audit", "Model Audit")}
            {link("/settings", "Settings")}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <div className="text-right leading-tight">
              <div className="font-medium">{user.username}</div>
              <div className="text-xs text-slate-500">{ROLES[user.role]}</div>
            </div>
            <button className="btn-ghost" onClick={() => logout().then(() => nav("/login"))}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1">
        <div className="max-w-6xl mx-auto px-5 py-6">{children}</div>
      </main>
      {!b.hide_footer && (
        <footer className="text-center text-xs text-slate-400 py-4">
          {b.footer_text || ""}
        </footer>
      )}
    </div>
  );
}
