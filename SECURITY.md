# Xyberah — Security Posture

This document summarises how Xyberah protects data and itself. It is written for
security teams evaluating the platform. For setup see [SETUP.md](SETUP.md).

## Responsible disclosure
Report vulnerabilities to **security@xyberah.com**. Please do not open public issues
for security reports. We aim to acknowledge within a few business days.

## Authentication & access
- **Sessions**: HttpOnly, SameSite=Lax cookies (JWT signed with the instance secret).
- **CSRF**: state-changing requests require an `X-Requested-With: xyberah` header.
- **2FA**: per-user TOTP (authenticator app) and/or email one-time codes.
- **SSO**: OIDC (Auth-Code + PKCE, JWKS id-token validation) and SAML 2.0.
- **SCIM 2.0**: IdP-driven provisioning/deprovisioning, scoped per company token.
- **RBAC**: global_admin > company_admin > analyst > viewer, enforced server-side.
- **API tokens**: bearer tokens for CI/automation; only the hash is stored; a token
  acts as its creating user, so tenancy and role apply.
- **Brute-force protection**: login rate limiting; bcrypt password hashing.

## Multi-tenancy & isolation
Every record carries a `company_id`. Non-global users are confined to their own
company on every query and object access (404, not 403, to avoid existence leaks).

## Encryption & secrets
- **At rest**: TOTP seeds, SMTP/SSO client secrets, saved targets, browser sessions,
  alert webhook URLs and SCIM tokens are encrypted with Fernet (AES), keyed from the
  instance secret (`XYBERAH_SECRET_KEY`). Only hashes are stored for passwords and
  API/SCIM tokens.
- **In transit**: HTTPS everywhere (self-signed by default; upload your own cert).
- **Key management**: the instance key lives in the data volume today. KMS/Vault
  backing and key rotation are on the roadmap; back up the key securely.

## Auditability
Append-only, **hash-chained** audit log: each row's hash covers the previous row's,
so any deletion or edit is detectable. Verify via Settings → Audit log → Verify
integrity. Signed compliance attestations (HMAC over the content digest, bound to the
audit-chain head) are exportable per campaign.

## Data governance
Per company: optional **PII/secret redaction** of stored findings, **retention**
auto-deletion of old campaigns, and monthly **cost/token budgets** with enforcement.

## Data flows (high level)
1. Browser → Caddy (TLS) → FastAPI backend.
2. Backend runs scanners (Promptfoo/garak/PyRIT/Inspect/DeepTeam) in isolated venvs
   as subprocesses against the configured target.
3. Model-provider API keys are read from the backend environment, never stored with
   campaigns. Custom HTTP targets reference secrets via headers encrypted at rest.
4. Findings, reports and audit entries are stored in the data volume (SQLite today).
5. Optional egress: configured model APIs, alert webhooks (Slack/Teams), SMTP, SSO
   IdP, and on-demand dataset fetches — all operator-configured.

## Supply chain
CI runs dependency advisories (`pip-audit`, `npm audit`), a filesystem vulnerability
scan (Trivy), and generates a CycloneDX **SBOM** artifact on every build. Bundled
open-source components and their licenses are listed in [NOTICE](NOTICE).

## Responsible use
Xyberah performs adversarial testing. Use it only against systems you own or are
explicitly authorised to test, in compliance with applicable law.
