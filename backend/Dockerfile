# Xyberah backend: FastAPI + Promptfoo (orchestrator) + garak / PyRIT / Inspect AI venvs
# Node comes from the official glibc node image so native promptfoo modules match this base.
FROM node:24-bookworm-slim AS node

# ModelAudit scanner venv (needs cargo to build picklescan; cargo stays out of the final image)
FROM python:3.12-bookworm AS modelaudit-build
ARG MODELAUDIT_VERSION=0.2.52
RUN apt-get update && apt-get install -y --no-install-recommends cargo \
 && rm -rf /var/lib/apt/lists/* \
 && python -m venv /opt/tools/modelaudit \
 && /opt/tools/modelaudit/bin/pip install --no-cache-dir "modelaudit==${MODELAUDIT_VERSION}"

FROM python:3.12-bookworm AS base
ENV PIP_ROOT_USER_ACTION=ignore PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_RETRIES=8 PIP_DEFAULT_TIMEOUT=180

# Node + Promptfoo engine (same version as the Xyberah image)
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# WeasyPrint (PDF) runtime libraries + CA certs
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi8 \
      libjpeg62-turbo fonts-dejavu-core ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# ---- Promptfoo engine (glibc build) ---------------------------------------- #
ARG PROMPTFOO_VERSION=0.124.1
RUN npm install -g "promptfoo@${PROMPTFOO_VERSION}" && npm cache clean --force

# ---- isolated tool virtualenvs --------------------------------------------- #
# Built at /opt/tools, then moved to /opt/tools-seed. The entrypoint seeds the
# (empty) /opt/tools volume on first boot, so tool updates persist and the
# venvs keep their original absolute paths.
ARG GARAK_VERSION=0.17.0
ARG PYRIT_VERSION=1.1.0
ARG INSPECT_VERSION=0.3.286
# All three venvs + the move happen in ONE layer so the seed copy does not get
# duplicated against a parent layer (which previously ~doubled the image size).
RUN python -m venv /opt/tools/garak \
 && /opt/tools/garak/bin/pip install --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cpu "garak==${GARAK_VERSION}" \
 && python -m venv /opt/tools/pyrit \
 && /opt/tools/pyrit/bin/pip install --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cpu "pyrit==${PYRIT_VERSION}" \
 && python -m venv /opt/tools/inspect \
 && /opt/tools/inspect/bin/pip install --no-cache-dir "inspect-ai==${INSPECT_VERSION}" \
 && mv /opt/tools /opt/tools-seed
COPY --from=modelaudit-build /opt/tools/modelaudit /opt/tools-seed/modelaudit

# ---- backend app ----------------------------------------------------------- #
# xmlsec/libxml2 for SAML (python3-saml). Placed here (after the tool venvs) so
# changing it does not bust the expensive venv layers above.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libxmlsec1-dev libxml2-dev libxmlsec1-openssl pkg-config \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/xyberah-app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY engine ./engine
COPY entrypoint.sh /usr/local/bin/xyberah-entrypoint
# Strip any CRLF so the shebang works when built from a Windows checkout
RUN sed -i 's/\r$//' /usr/local/bin/xyberah-entrypoint && chmod +x /usr/local/bin/xyberah-entrypoint

# Playwright + Chromium for the "Browser (web chat UI)" target bridge.
# Installed into the engine dir so Promptfoo's JS provider can require('playwright').
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN cd engine && npm init -y >/dev/null 2>&1 && \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install playwright@1.48.2 && \
    npx playwright install --with-deps chromium && \
    npm cache clean --force && rm -rf /root/.npm

ENV XYBERAH_DATA_DIR=/data \
    XYBERAH_TOOLS_DIR=/opt/tools \
    XYBERAH_ENGINE_BIN=promptfoo \
    XYBERAH_ENGINE_DIR=/opt/xyberah-app/engine \
    XYBERAH_STATIC_DIR=/opt/xyberah-app/static \
    XYBERAH_BRANDING_FILE=/config/branding.yaml \
    PROMPTFOO_DISABLE_TELEMETRY=1 \
    PROMPTFOO_DISABLE_UPDATE=1

EXPOSE 8000
ENTRYPOINT ["xyberah-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
