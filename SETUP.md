# Xyberah — Setup, Configuration & Operations

Detailed guide for installing, configuring, hardening and operating Xyberah.
For a high-level overview and feature list, see [README.md](README.md).

---

## 1. Requirements

- **Docker Desktop** (Windows/macOS) or **Docker Engine + Compose v2** (Linux).
- ~15 GB disk for the images (the scanners and Chromium are bundled).
- Outbound internet for the first build (to pull the scanners) and for scans that call hosted
  model APIs. Scans against local/HTTP targets can run fully offline.

## 2. Install

**One command:**
- Windows: `.\install.ps1`
- Linux/macOS: `./install.sh` (or `make install`)

The installer writes `.env`, generates a strong admin password, builds the images and starts
the stack, then prints the URL and credentials.

**Manual:**
```bash
cp .env.example .env         # edit as needed
docker compose build         # first build downloads scanners (~15 min)
docker compose up -d
```

## 3. First administrator

Two ways to create the first **global admin**:
- **Headless**: set `XYBERAH_ADMIN_USERNAME` and `XYBERAH_ADMIN_PASSWORD` in `.env` before first
  start; the admin is created automatically.
- **In-browser**: leave `XYBERAH_ADMIN_PASSWORD` empty; the first visit shows a one-time setup
  screen to create the admin.

Passwords must be at least 10 characters.

## 4. Environment variables (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `XYBERAH_HTTPS_PORT` | `8443` | Host port for HTTPS. |
| `XYBERAH_ADMIN_USERNAME` | `admin@xyberah.local` | First global admin (headless bootstrap). |
| `XYBERAH_ADMIN_PASSWORD` | _(empty)_ | Set to bootstrap headlessly; empty = in-browser setup. |
| `XYBERAH_COOKIE_SECURE` | `true` | Send session cookie only over HTTPS. |
| `XYBERAH_SESSION_HOURS` | `12` | Session lifetime. |
| `XYBERAH_GRADER` | `openai:chat:gpt-4.1-mini` | Model used for LLM-rubric grading and AI prompt generation. |
| `XYBERAH_MAX_CONCURRENT_CAMPAIGNS` | `1` | Default per-company concurrency (also set per company). |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` / `AZURE_API_KEY` / `HF_API_TOKEN` | _(empty)_ | Keys for provider targets and the grader. |
| `XYBERAH_SECRET_KEY` | _(generated, persisted)_ | Signs sessions and derives the at-rest encryption key. Keep it safe. |

After changing `.env`: `docker compose up -d`.

> **Grader key**: LLM-rubric grading, the AI attack-pack generator and some Promptfoo plugins
> need the grader model's key (by default `OPENAI_API_KEY`). Keyword grading and most scanners
> work without it.

## 5. TLS / HTTPS

- A self-signed cert is generated on first boot (persisted so it survives restarts). Browsers
  warn once — continue past it.
- Upload your own cert+key under **Settings → TLS certificate**; it hot-reloads.
- For production, terminate TLS at your edge or install a trusted cert, then you may enable HSTS
  at the edge.

## 6. Email (SMTP)

**Settings → Email (SMTP)** (global admin): host, port, credentials, from address, TLS. Used for
user invites and email one-time codes. Without SMTP, codes/invites appear in a dev outbox in the
logs.

## 7. SSO (OIDC & SAML) and SCIM

**Settings → SSO & SCIM** (global admin). First set the **public base URL** (e.g.
`https://xyberah.example:8443`) — it builds the redirect/ACS URLs.

**OIDC** (Okta, Entra/Azure AD, Google, Auth0, Keycloak):
1. In your IdP, create an app with redirect URI `https://<base>/api/auth/oidc/callback`.
2. Enter the **issuer** (discovery base), **client ID** and **client secret**, enable OIDC.

**SAML 2.0:**
1. In your IdP, create a SAML app. SP metadata: `https://<base>/api/auth/saml/metadata`;
   ACS (reply) URL: `https://<base>/api/auth/saml/acs`.
2. Enter the IdP **entity ID**, **SSO URL** and **x509 certificate**, enable SAML.

**Provisioning**: map **email domains → companies** (new SSO users join the matched company with
that domain's default role). Turn off auto-provisioning to require an admin to pre-create users.

**SCIM 2.0**: create a SCIM token (scoped to one company), give your IdP the token and base URL
`https://<base>/scim/v2`. Supports user create / update / deactivate.

## 8. Alerts & SIEM

**Settings → Alerts & SIEM** (company admin): add Slack / Teams / webhook channels, optionally
only above a risk score. Per-finding **CEF** export is available on each campaign's report row
for syslog/Splunk ingestion.

## 9. Data governance

**Settings → Data governance** (company admin): toggle **redaction** of PII/secrets in stored
findings, set a **retention** window (finished campaigns auto-deleted hourly past it), and set
monthly **cost/token budgets** with optional enforcement (blocks new campaigns when exceeded).

## 10. Scanners

**Settings → Scanners** shows installed vs latest versions for garak / PyRIT / Inspect AI /
ModelAudit and lets a global admin update each from PyPI without rebuilding.

## 11. CI/CD

Create an **API token** (Settings → API tokens), then call `POST /api/ci/scan` to run a scan and
get a pass/fail gate. See `ci/ci_scan.sh` and the Swagger docs at `/api/docs`.

## 12. Backups & upgrades

- **Backup**: `make backup` captures the data/config/certs volumes (SQLite DB, uploads, secret
  key, branding, certs). Store it securely — it includes the key material for encrypted secrets.
- **Upgrade**: pull the new code, `docker compose build`, `docker compose up -d`. The DB
  auto-migrates (new columns/tables are added on startup); existing data is preserved.

## 13. Production hardening

- Set a strong, backed-up `XYBERAH_SECRET_KEY` and keep `XYBERAH_COOKIE_SECURE=true`.
- Install a trusted TLS cert (or terminate at your edge) and set the **public base URL**.
- Use a real SMTP server; enable 2FA or SSO for all accounts.
- Set per-company concurrency, retention and budgets; enable redaction where findings may hold
  sensitive data.
- Restrict who holds global-admin; rotate API/SCIM tokens.

## 14. Troubleshooting

- **Docker build/500 errors (Windows/WSL)**: restart Docker Desktop, wait for the engine, rerun.
- **"Failed to fetch" / can't reach the app**: the self-signed cert must be accepted once; HSTS
  is intentionally off for self-signed. Confirm the proxy container is up (`make logs`).
- **First build is slow (~15 min)**: it downloads garak/PyRIT/Inspect/ModelAudit and Chromium;
  subsequent builds are cached.
- **AI generation / rubric grading fails**: the grader model key isn't set (see §4).
- **SSO sign-in fails**: check the public base URL matches the IdP's redirect/ACS URL exactly,
  and that OIDC issuer / SAML cert are correct. Errors surface on the login page.
- **A scanner stage is skipped**: garak/PyRIT/Inspect don't support browser targets; Inspect
  doesn't support custom HTTP targets — those stages skip by design.

---

Built by [xyberah.com](https://xyberah.com).
