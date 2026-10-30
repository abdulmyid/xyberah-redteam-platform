# Xyberah backend: FastAPI + Promptfoo (orchestrator) + garak / PyRIT / Inspect AI venvs
# Node comes from the official glibc node image so native promptfoo modules match this base.
FROM node:24-bookworm-slim AS node

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
RUN python -m venv /opt/tools/garak \
 && /opt/tools/garak/bin/pip install --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cpu "garak==${GARAK_VERSION}"
RUN python -m venv /opt/tools/pyrit \
 && /opt/tools/pyrit/bin/pip install --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cpu "pyrit==${PYRIT_VERSION}"
RUN python -m venv /opt/tools/inspect \
 && /opt/tools/inspect/bin/pip install --no-cache-dir "inspect-ai==${INSPECT_VERSION}"
RUN mv /opt/tools /opt/tools-seed

# ---- backend app ----------------------------------------------------------- #
WORKDIR /opt/xyberah-app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY engine ./engine
COPY entrypoint.sh /usr/local/bin/xyberah-entrypoint
RUN chmod +x /usr/local/bin/xyberah-entrypoint

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
