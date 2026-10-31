# Xyberah — AI Red-Teaming & Security Evaluation Platform

A self-hosted, multi-tenant web platform that orchestrates **Promptfoo**, **NVIDIA garak**,
**Microsoft PyRIT**, **UK AISI Inspect AI** and **ModelAudit** behind one dashboard to test
LLM applications — and the agents, RAG pipelines and model files behind them — for jailbreaks,
prompt injection, data leakage, harmful output, insecure tool use, excessive agency and unsafe
model artifacts. White-label branding, RBAC, 2FA, SSO/SCIM, a tamper-evident audit log and
per-company data governance are built in.

Promptfoo is the orchestration core. garak runs its probe/detector suite, PyRIT runs multi-turn
attacks through a Promptfoo Python provider, Inspect AI runs agentic-safety tasks, ModelAudit
scans model files, and your **own prompts/datasets** run as graded evaluations. All results are
normalized into one findings model, one risk score, and one report (HTML / PDF / JSON / CSV /
CEF / signed attestation).

---

## Quick start (one command)

Prerequisites: **Docker Desktop** (or Docker Engine + Compose). Nothing else to install.

**Windows (PowerShell):** `.\install.ps1`
**Linux / macOS:** `./install.sh`   (or `make install`)

The installer creates `.env`, generates a strong admin password, builds the images (the first
build downloads the scanners, ~15 min) and starts everything. It then prints your URL and
credentials:

```
URL:      https://localhost:8443
Username: admin@xyberah.local
Password: <generated>
```

Open the URL. The TLS certificate is **self-signed by default**, so your browser warns once —
continue past it, or upload your company certificate under **Settings → TLS certificate**.
On a fresh install with no admin password set, the first visit walks you through creating the
global admin in the browser.

To add model keys for scans, put them in `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GOOGLE_API_KEY`, …) and `docker compose up -d`. Common commands: `make up`, `make down`,
`make logs`, `make backup`.

---

## Feature overview

**Scanning engines**
- **Promptfoo** — 70+ red-team plugins across OWASP-style collections + 25 strategies; one-click
  templates (OWASP LLM Top 10, PII, Agentic & RAG, …).
- **garak**, **PyRIT** (multi-turn), **Inspect AI** (agentic) — each in its own venv, updatable
  from PyPI in Settings → Scanners.
- **ModelAudit** — upload a model file (pickle / PyTorch / safetensors / GGUF / ONNX / ZIP) and
  scan it for malicious code and unsafe deserialization.
- **Custom prompts** — run your own prompt sets against a target, graded by LLM rubric and/or
  keyword rules.

**Targets** — OpenAI / Anthropic / Google Gemini / Azure OpenAI / AWS Bedrock / Hugging Face /
Ollama, a **Custom HTTP endpoint** (paste a `curl`, auto-detect the response path),
a **Web chat UI (browser)** driven by Playwright with recorded login macros and saved sessions,
an **MCP / tool-calling agent** (a base model wired to MCP servers over HTTP/SSE), and a built-in
**demo target** (no API key) for a first run. Any target can be saved and reused.

**Prompts, datasets & traffic replay**
- A reusable **Prompts & Datasets** library with per-set grading.
- Import datasets as **CSV / JSON / TXT**.
- **Replay real traffic**: import **OpenTelemetry/OTLP** trace JSON (GenAI spans) or **JSONL**
  logs (incl. OpenAI `messages`); user prompts are extracted and de-duplicated.
- **AI attack-pack generator** — auto-author domain-specific adversarial prompts from an app's
  purpose (uses the configured grader model).

**Continuous testing**
- **Scheduled scans** — daily / weekly / every-N-hours recurring campaigns.
- **Finding lifecycle** — triage status (open / triaged / fixed / accepted-risk / false-positive),
  notes, and **retest** a single finding against the live target.
- **Drift / regression** — diff a run against a previous one (new / fixed / still-failing +
  risk delta); risk-score trend on the dashboard.
- **Interactive console** — probe a target one prompt at a time and save the interesting ones.

**Reporting & integrations**
- Reports in **HTML / PDF / JSON / CSV**, framework mappings (OWASP LLM Top 10, NIST AI RMF,
  MITRE ATLAS, EU AI Act), attack-method and strategy breakdowns, cost/latency analytics,
  remediation guidance.
- **Signed compliance attestation** (PDF) — tamper-evident HMAC over the content digest, bound
  to the audit-log chain head, with per-framework pass/fail.
- **SIEM export** — ArcSight **CEF** per finding for syslog / Splunk.
- **Alerts** — Slack / Teams / generic webhook on scan completion or above a risk threshold.
- **CI/CD quality gate** — a bearer-token API that runs a scan and fails the build on
  configurable thresholds.

**Enterprise**
- **SSO** — OIDC (Auth-Code + PKCE) and SAML 2.0, with **email-domain → company** just-in-time
  provisioning.
- **SCIM 2.0** — IdP-driven user create / update / deactivate (`/scim/v2`).
- **Data governance** — per-company PII/secret **redaction** of stored findings, **retention**
  auto-delete, and monthly **cost/token budgets** with optional enforcement.

---

## API & Swagger

Every capability is a REST endpoint. Interactive docs (Swagger UI) are at **`/api/docs`**
(ReDoc at `/api/redoc`, raw schema at `/api/openapi.json`) — also linked from
**Settings → API tokens**.

- **Automation/CI**: `Authorization: Bearer <api-token>` (create under Settings → API tokens).
  The token acts as its creating user, so tenancy and role apply.
- **CI gate**: `POST /api/ci/scan` runs a campaign and returns a pass/fail gate result; see
  `ci/ci_scan.sh`.

```bash
curl -H "Authorization: Bearer $XYBERAH_TOKEN" \
     -H "Content-Type: application/json" \
     https://xyberah.example/api/ci/scan -d @scan.json
```

---

## Architecture

```
  Browser ──HTTPS──▶  proxy (Caddy)  ── serves the React app, TLS (self-signed or your cert),
                                        reverse-proxies /api, /uploads, /scim
                            │
                      backend (FastAPI)
                        • auth, RBAC, tenancy, 2FA, SSO/SCIM, audit
                        • campaign orchestrator (staged, pause/resume/stop)
                        • scheduler thread (recurring scans + retention sweep)
                        • report builder (HTML/PDF/JSON/CSV/CEF/attestation)
                        • alerts (Slack/Teams/webhook)
                        Promptfoo (Node) ◀ orchestrates
                        garak / PyRIT / Inspect / ModelAudit venvs ─▶ run against target
```

A **campaign** runs its selected engines as sequential **stages** (promptfoo → custom → pyrit →
garak → inspect). You can **pause between stages**, **resume**, or **stop** (kills the running
stage). Live progress, logs and findings stream to the browser over SSE.

---

## Roles (RBAC)

| Role | Can do |
|---|---|
| **Global admin** | Manage companies, all users, SMTP, TLS, scanners, **SSO/SCIM**, any company's governance; verify audit chain |
| **Company admin** | Manage their company's users/invites, branding, audit log, **alerts**, **data governance** |
| **Analyst** | Create/run/pause/stop campaigns & schedules; prompts/datasets; console; retest/triage; reports; API tokens |
| **Viewer** | Read campaigns and reports only |

Every company's data is isolated by `company_id`, enforced on every query and object access.

## Security

- **Multi-tenant isolation** on every query and object.
- **SSO** (OIDC + SAML) and **2FA** (TOTP + email OTP); SCIM for lifecycle management.
- **Tamper-evident audit log**: hash-chained; Settings → Audit log → *Verify integrity*.
- **Secrets encrypted at rest** (TOTP seeds, SMTP/SSO secrets, saved targets, browser sessions,
  alert webhook URLs) with a key derived from the instance secret.
- **Data governance**: optional redaction of PII/secrets in stored findings, retention policies,
  and spend budgets.
- **CSRF** (SameSite cookies + `X-Requested-With`), login rate limiting, bcrypt hashing,
  HttpOnly session cookies.
- **HTTPS everywhere** with an automatic self-signed cert and one-click upload of your own.
- **Offline-capable** scans; no telemetry.

See [SETUP.md](SETUP.md) for detailed setup, upgrades, production hardening and troubleshooting.

---

Built by [xyberah.com](https://xyberah.com).
