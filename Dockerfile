# Menu Hero Core — multi-stage production build.
#
# Stages (in this order; the LAST stage `app` is the default target, which is
# what Elastic Beanstalk builds when it finds this Dockerfile):
#
#   frontend-build  node:22-alpine   npm ci + `nuxt build`  -> frontend/.output
#   frontend        node:22-alpine   runtime for docker-compose (Nitro on :3000)
#   frontend-dev    node:22-alpine   `nuxi dev` on :3000, source bind-mounted (compose dev)
#   backend-build   python:3.13      uv sync of backend/ (+ ../agents path dep) -> /app/backend/.venv
#   backend         python:3.13      runtime for docker-compose (uvicorn on :8000)
#   backend-dev     python:3.13      `uvicorn --reload` on :8000, source bind-mounted (compose dev)
#   app             python:3.13      nginx :8080 -> FastAPI :8000 + Nuxt :3000, all under supervisord
#
# The `*-dev` stages are only ever built by docker-compose.dev.yml. They install
# dependencies and nothing else: the source arrives as a bind mount at run time.
#
# Build/run recipes live in deploy/README.md. Base tags are pinned to a major
# line so security patches flow in on rebuild without silent major upgrades.

ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# =============================================================================
# frontend-build: compile the Nuxt 4 app into a self-contained Nitro bundle.
# =============================================================================
FROM ${NODE_IMAGE} AS frontend-build

ENV NUXT_TELEMETRY_DISABLED=1 \
    CI=true

WORKDIR /src/frontend

# Install dependencies first so this layer is cached until the lockfile changes.
# `--ignore-scripts` skips the `postinstall = "nuxt prepare"` hook, which needs
# the full source tree (copied below) to be useful; `nuxt build` regenerates
# everything `nuxt prepare` would have produced.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# Now the rest of the source (.dockerignore keeps node_modules/.output/.nuxt out).
COPY frontend/ ./
RUN npm run build

# =============================================================================
# frontend: minimal Node runtime serving the Nitro bundle (used by docker-compose).
# =============================================================================
FROM ${NODE_IMAGE} AS frontend

ENV NODE_ENV=production \
    NITRO_PORT=3000 \
    NITRO_HOST=0.0.0.0 \
    PORT=3000 \
    HOST=0.0.0.0 \
    NUXT_API_PROXY_TARGET=http://127.0.0.1:8000

WORKDIR /app/frontend

# The node image ships an unprivileged `node` user (uid 1000).
COPY --from=frontend-build --chown=node:node /src/frontend/.output ./.output

USER node

# Listens on 3000 (docker-compose publishes it). No EXPOSE here on purpose:
# Elastic Beanstalk reads the FIRST `EXPOSE` in this file to pick the port its
# host nginx proxies to, and that must be the `app` stage's 8080.
# Nitro honours NITRO_PORT/NITRO_HOST (and PORT/HOST) at start-up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", ".output/server/index.mjs"]

# =============================================================================
# frontend-dev: `nuxi dev` with HMR, for docker-compose.dev.yml.
#
# Only the lockfile is copied — frontend/ itself is bind-mounted at run time, and
# a named volume keeps this stage's Linux `node_modules` from being shadowed by
# the host's (macOS-built, and wrong for this image).
# =============================================================================
FROM ${NODE_IMAGE} AS frontend-dev

ENV NUXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=development

WORKDIR /app/frontend

# `--ignore-scripts` skips the `postinstall = "nuxt prepare"` hook: there is no
# source tree yet, and `nuxi dev` regenerates .nuxt/ on start anyway.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# `--host 0.0.0.0` overrides `devServer.host: '127.0.0.1'` in nuxt.config.ts, which
# would otherwise bind to the container's loopback and be unreachable from the host.
# Runs as root on purpose: the bind-mounted source has host ownership, and .nuxt/
# has to be writable inside it.
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=6 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

# =============================================================================
# backend-build: resolve the locked Python environment with uv.
# =============================================================================
FROM ${PYTHON_IMAGE} AS backend-build

# uv binary straight from the official image — no pip install step needed.
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

# UV_PYTHON pins the image interpreter so a stricter backend/.python-version
# (e.g. "3.13.5") can never make uv look for a download we forbid.
ENV UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.13 \
    UV_NO_PROGRESS=1

# backend/pyproject.toml depends on menu-hero-agents via `path = "../agents"`,
# so the two directories must sit side by side exactly as in the repo.
WORKDIR /app/backend
COPY agents/ /app/agents/

# Dependencies only (cached until uv.lock / pyproject.toml change). --no-editable
# turns the editable ../agents source into a real wheel inside the venv, which
# is why the runtime stages never need /app/agents at all.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project

# Then the application itself.
COPY backend/ ./
RUN uv sync --frozen --no-dev --no-editable

# =============================================================================
# backend: FastAPI runtime on :8000 (used by docker-compose).
# =============================================================================
FROM ${PYTHON_IMAGE} AS backend

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/backend/.venv/bin:${PATH}" \
    APP_ENV=production

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /app --create-home \
       --shell /usr/sbin/nologin app

WORKDIR /app/backend

# The venv is copied to the same absolute path it was created at, so the
# interpreter symlinks inside it stay valid.
COPY --from=backend-build --chown=app:app /app/backend/.venv ./.venv
COPY --from=backend-build --chown=app:app /app/backend/app ./app
COPY --chown=app:app backend/pyproject.toml ./pyproject.toml

USER app

# Listens on 8000 (docker-compose publishes it); no EXPOSE for the same
# Elastic Beanstalk first-EXPOSE reason as the frontend stage.
# python:slim has no curl, so probe with the standard library instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# =============================================================================
# backend-dev: `uvicorn --reload` over bind-mounted source, for docker-compose.dev.yml.
#
# The venv lives at /opt/venv, NOT /app/backend/.venv: that path is inside the
# bind mount at run time and would be shadowed by the host's macOS-built venv.
# Dev dependencies are installed too, so `docker compose exec backend pytest` works.
# =============================================================================
FROM ${PYTHON_IMAGE} AS backend-dev

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.13 \
    UV_NO_PROGRESS=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    APP_ENV=development

WORKDIR /app/backend

# Both packages are installed *editable*, so the import paths they resolve to
# (/app/backend and /app/agents) are exactly the paths compose bind-mounts over —
# which is what makes an edit on the host visible to the interpreter at once.
COPY agents/ /app/agents/
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project
COPY backend/ ./
RUN uv sync --frozen

# The reload dirs are named explicitly: uvicorn watches only its working
# directory by default, which would miss every edit under /app/agents.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", \
     "--reload-dir", "/app/backend/app", "--reload-dir", "/app/agents"]

# =============================================================================
# app (DEFAULT TARGET): single container for Elastic Beanstalk.
#
#   host nginx (EB) -> :8080 in-container nginx -> /api/  -> uvicorn  :8000
#                                                -> /      -> nitro    :3000
#
# supervisord keeps all three alive and forwards their logs to the container's
# stdout/stderr. Everything runs as the unprivileged `app` user.
# =============================================================================
FROM ${PYTHON_IMAGE} AS app

ENV DEBIAN_FRONTEND=noninteractive

# nginx + supervisor from Debian, Node 22 from NodeSource — one layer so the
# apt lists are cleaned in the same step they were created.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        nginx supervisor curl ca-certificates gnupg; \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -; \
    apt-get install -y --no-install-recommends nodejs; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*; \
    node --version; \
    nginx -v; \
    supervisord --version

# Unprivileged runtime user. uid/gid 1001 to avoid clashing with anything
# the base image might define.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /app --create-home \
       --shell /usr/sbin/nologin app

# Make nginx runnable without root: deploy/nginx/nginx.conf already points the
# pid and every temp path at /tmp and logs at stdout/stderr, but nginx also
# opens its compiled-in default error log before it reads the config, so hand
# those directories to `app` and route the default log files to the console
# (same trick as the official nginx image).
RUN mkdir -p /var/log/nginx /var/lib/nginx /var/cache/nginx \
    && ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log \
    && chown -R app:app /var/log/nginx /var/lib/nginx /var/cache/nginx

WORKDIR /app

# Backend: locked venv + application source.
COPY --from=backend-build --chown=app:app /app/backend/.venv /app/backend/.venv
COPY --from=backend-build --chown=app:app /app/backend/app  /app/backend/app
COPY --chown=app:app backend/pyproject.toml /app/backend/pyproject.toml

# Frontend: the Nitro bundle only.
COPY --from=frontend-build --chown=app:app /src/frontend/.output /app/frontend/.output

# Process + proxy configuration.
COPY --chown=app:app deploy/nginx/nginx.conf  /app/deploy/nginx/nginx.conf
COPY --chown=app:app deploy/supervisord.conf  /app/deploy/supervisord.conf

# PORT is what Elastic Beanstalk expects the container to listen on; the Nuxt
# process gets its own PORT=3000 from supervisord.conf. UVICORN_WORKERS is read
# by supervisord.conf (`%(ENV_UVICORN_WORKERS)s`) — override it per environment.
ENV APP_ENV=production \
    PORT=8080 \
    NUXT_API_PROXY_TARGET=http://127.0.0.1:8000 \
    UVICORN_WORKERS=2 \
    NODE_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/backend/.venv/bin:${PATH}"

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

USER app

CMD ["supervisord", "-c", "/app/deploy/supervisord.conf"]
