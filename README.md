# Xyberah — AI Red-Teaming & Security Evaluation Platform

A self-hosted, multi-tenant web platform that orchestrates **Promptfoo**, **NVIDIA garak**,
**Microsoft PyRIT** and **UK AISI Inspect AI** behind one dashboard to test LLM applications
for jailbreaks, prompt injection, data leakage, harmful output, insecure tool use and
agentic-reasoning failures — with white-label branding, RBAC, 2FA and a tamper-evident audit log.

Promptfoo is the orchestration core. garak runs its probe/detector suite, PyRIT runs
multi-turn attacks through a Promptfoo Python provider, and Inspect AI runs agentic-safety
tasks. All results are normalized into one findings model, one risk score, and one report
(HTML / PDF / JSON / CSV).

---

## Quick start (one command)

Prerequisites: **Docker Desktop** (or Docker Engine + Compose). Nothing else to install.

**Windows (PowerShell):**
```powershell
.\install.ps1
```

**Linux / macOS:**
```bash
./install.sh         # or:  make install
```

The installer creates `.env`, generates a strong admin password, builds the images
(the first build downloads the scanners, ~15 min) and starts everything. When it finishes it
prints your URL and credentials:

```
URL:      https://localhost:8443
Username: admin@xyberah.local
Password: <generated>
```

Open the URL. The TLS certificate is **self-signed by default**, so your browser warns once —
continue past it, or upload your company certificate under **Settings → TLS certificate**.

To add model keys for scans, put them in `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) and
`docker compose up -d`.

Common commands: `make up`, `make down`, `make logs`, `make backup`.

---

## Architecture

```
                         ┌───────────────────────────────────────────┐
  Browser ──HTTPS──▶     │  proxy (Caddy)                            │
                         │   • serves the React app over TLS         │
                         │   • auto self-signed cert, or your upload │
                         │   • reverse-proxies /api, /uploads        │
                         └───────────────┬───────────────────────────┘
                                         │
                         ┌───────────────▼───────────────────────────┐
                         │  backend (FastAPI)                        │
                         │   • auth, RBAC, tenancy, 2FA, audit       │
                         │   • campaign orchestrator (staged)        │
                         │   • report builder (HTML/PDF/JSON/CSV)    │
                         │                                           │
                         │   Promptfoo (Node)  ◀ orchestrates        │
                         │   garak    venv  ─┐                       │
                         │   PyRIT    venv  ─┼─▶ run against target  │
                         │   Inspect  venv  ─┘                       │
                         └───────────────────────────────────────────┘
```

A **campaign** runs its selected tools as sequential **stages**. You can **pause between
stages** (the running stage finishes, then it holds), **resume**, or **stop** (kills the
running stage immediately). Live progress, logs and findings stream to the browser over SSE.

---

## Project structure

```
xyberah/
├── install.sh / install.ps1      One-command installers
├── Makefile                      up / down / logs / backup
├── docker-compose.yml            backend + proxy, shared volumes
├── .env.example                  Configuration template
│
├── backend/                      FastAPI service + orchestrator + scanners
│   ├── Dockerfile                Python + Node(Promptfoo) + garak/PyRIT/Inspect venvs
│   ├── entrypoint.sh             Seeds tool venvs, default branding
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py               App wiring, audit middleware, startup bootstrap
│   │   ├── config.py             Env-driven settings
│   │   ├── db.py / models.py     SQLModel schema (multi-tenant)
│   │   ├── auth.py               Sessions, RBAC, tenancy guards
│   │   ├── mfa.py                TOTP + email OTP
│   │   ├── crypto.py             Fernet encryption for secrets at rest
│   │   ├── email_service.py      SMTP + dev outbox fallback
│   │   ├── branding.py           Per-company white-label
│   │   ├── tls_service.py        Custom cert validation/install
│   │   ├── audit.py              Hash-chained audit log + middleware
│   │   ├── schemas.py
│   │   ├── routers/              auth, admin, campaigns, reports, settings, tls, audit
│   │   ├── orchestrator/
│   │   │   ├── runner.py         Staged campaign engine (pause/resume/stop)
│   │   │   ├── targets.py        Target → provider translation
│   │   │   ├── catalog.py        Plugin/category catalog + mapping
│   │   │   ├── promptfoo_config.py / promptfoo_runner.py
│   │   │   ├── garak_runner.py   garak CLI + report parsing
│   │   │   ├── pyrit_attacks.py  PyRIT attack catalog
│   │   │   ├── inspect_runner.py Inspect AI eval + log parsing
│   │   │   ├── tools.py          Version info + "update from PyPI"
│   │   │   └── events.py         SSE event bus (per campaign)
│   │   └── reports/              aggregate.py, charts.py, builder.py, templates/
│   └── engine/
│       ├── providers/pyrit_provider.py     Promptfoo Python provider → PyRIT
│       ├── inspect_tasks/xyberah_agentic.py Agentic/tool-use/reasoning tasks
│       └── branding.default.yaml
│
├── proxy/                        HTTPS frontend proxy
│   ├── Dockerfile                Builds the React app, serves via Caddy
│   ├── Caddyfile
│   └── entrypoint.sh             Self-signed default + cert hot-reload watcher
│
└── frontend/                     React + Vite + Tailwind SPA
    ├── src/pages/                Login, Dashboard, NewCampaign, CampaignDetail, Settings
    │   └── settings/             Branding, Security(2FA), Users, Companies, Email, Tls, Tools, Audit
    ├── src/components/           Layout, UI (gauge, badges)
    └── src/lib/                  api client, app context (auth + branding)
```

---

## Roles (RBAC)

| Role | Can do |
|---|---|
| **Global admin** | Manage companies, all users, SMTP, TLS cert, scanner updates, verify audit chain |
| **Company admin** | Manage their company's users/invites, branding, audit log |
| **Analyst** | Create, run, pause/stop campaigns; generate and share reports |
| **Viewer** | Read campaigns and reports only |

Every company's data (campaigns, findings, branding, invites, audit) is isolated by `company_id`.

## Security features

- **Multi-tenant isolation** enforced on every query and object access.
- **2FA** per user: TOTP authenticator app (QR enrolment) and/or email one-time codes.
- **Tamper-evident audit log**: every change is hash-chained; `Settings → Audit log → Verify
  integrity` recomputes the chain and flags any altered or deleted entry.
- **Secrets encrypted at rest** (TOTP seeds, SMTP password) with a key derived from the
  instance secret.
- **CSRF protection** (SameSite cookies + required `X-Requested-With` header), login rate
  limiting, bcrypt password hashing, HttpOnly session cookies.
- **HTTPS everywhere** with an automatic self-signed cert and one-click upload of your own.
- **Fully offline-capable** scans (set `PROMPTFOO_DISABLE_REMOTE_GENERATION=true`); no
  telemetry.

See [SETUP.md](SETUP.md) for detailed setup, upgrades, production hardening and troubleshooting.

---

Built by [xyberah.com](https://xyberah.com).
