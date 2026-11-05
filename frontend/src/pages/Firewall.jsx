import { useState } from "react";
import { atLeast } from "../lib/api";
import { useApp } from "../lib/context.jsx";
import Overview from "./firewall/Overview.jsx";
import Traffic from "./firewall/Traffic.jsx";
import Policies from "./firewall/Policies.jsx";
import Consumers from "./firewall/Consumers.jsx";
import Providers from "./firewall/Providers.jsx";
import GatewaySettings from "./firewall/GatewaySettings.jsx";

export default function Firewall() {
  const { user } = useApp();
  const tabs = [
    { id: "overview", label: "Overview", show: true, el: <Overview /> },
    { id: "traffic", label: "Traffic log", show: true, el: <Traffic /> },
    { id: "policies", label: "Policies & rules", show: true, el: <Policies /> },
    { id: "consumers", label: "Consumer keys", show: atLeast(user.role, "company_admin"), el: <Consumers /> },
    { id: "providers", label: "Upstream providers", show: atLeast(user.role, "company_admin"), el: <Providers /> },
    { id: "settings", label: "Gateway settings", show: user.role === "global_admin", el: <GatewaySettings /> },
  ].filter((t) => t.show);
  const [active, setActive] = useState("overview");

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold">AI Firewall</h1>
        <p className="text-sm text-slate-500 mt-1">
          An OpenAI/Anthropic-compatible gateway that inspects every prompt and response: injection &amp; jailbreak
          guardrails, data-loss prevention, toxic/code output controls, rate limiting and a tamper-evident audit trail.
        </p>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-slate-200 pb-2">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setActive(t.id)}
            className={`tab ${active === t.id ? "tab-active" : "hover:bg-slate-100"}`}>{t.label}</button>
        ))}
      </div>
      {tabs.find((t) => t.id === active)?.el}
    </div>
  );
}
