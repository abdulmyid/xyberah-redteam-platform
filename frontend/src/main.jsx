import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppProvider, useApp } from "./lib/context.jsx";
import Login from "./pages/Login.jsx";
import AcceptInvite from "./pages/AcceptInvite.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import NewCampaign from "./pages/NewCampaign.jsx";
import CampaignDetail from "./pages/CampaignDetail.jsx";
import ModelAudit from "./pages/ModelAudit.jsx";
import Prompts from "./pages/Prompts.jsx";
import Schedules from "./pages/Schedules.jsx";
import Settings from "./pages/Settings.jsx";
import Layout from "./components/Layout.jsx";
import "./index.css";

function Protected({ children }) {
  const { user, loading } = useApp();
  if (loading) return <div className="p-10 text-slate-500">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/invite/:token" element={<AcceptInvite />} />
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/campaigns/new" element={<Protected><NewCampaign /></Protected>} />
      <Route path="/campaigns/:id" element={<Protected><CampaignDetail /></Protected>} />
      <Route path="/prompts" element={<Protected><Prompts /></Protected>} />
      <Route path="/schedules" element={<Protected><Schedules /></Protected>} />
      <Route path="/model-audit" element={<Protected><ModelAudit /></Protected>} />
      <Route path="/settings" element={<Protected><Settings /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AppProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AppProvider>
  </React.StrictMode>
);
