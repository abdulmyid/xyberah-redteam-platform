// Thin fetch wrapper. Sends the CSRF header on mutations and surfaces API errors.
const CSRF = { "X-Requested-With": "xyberah" };

async function handle(res) {
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || res.statusText;
    const err = new Error(typeof msg === "string" ? msg : "Request failed");
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  get: (path) => fetch(path, { credentials: "same-origin" }).then(handle),
  post: (path, body) =>
    fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...CSRF },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(handle),
  put: (path, body) =>
    fetch(path, {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...CSRF },
      body: JSON.stringify(body),
    }).then(handle),
  patch: (path, body) =>
    fetch(path, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...CSRF },
      body: JSON.stringify(body),
    }).then(handle),
  del: (path) =>
    fetch(path, { method: "DELETE", credentials: "same-origin", headers: CSRF }).then(handle),
  upload: (path, formData) =>
    fetch(path, { method: "POST", credentials: "same-origin", headers: CSRF, body: formData }).then(handle),
};

export const ROLES = {
  global_admin: "Global admin",
  company_admin: "Company admin",
  analyst: "Analyst",
  viewer: "Viewer",
};

export function atLeast(role, min) {
  const rank = { viewer: 0, analyst: 1, company_admin: 2, global_admin: 3 };
  return (rank[role] ?? -1) >= rank[min];
}
