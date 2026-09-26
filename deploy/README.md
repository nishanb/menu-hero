# Deployment — Menu Hero Core

Everything needed to run the monorepo as **one container on one domain**:

```
                    ┌──────────────────────── container (EXPOSE 8080) ────────────────────────┐
browser ──:80──▶ EB host nginx ──:8080──▶ in-container nginx ──┬── /api/* ──▶ uvicorn  127.0.0.1:8000 (FastAPI)
                                       (deploy/nginx/nginx.conf)└── /*     ──▶ node     127.0.0.1:3000 (Nuxt/Nitro)
                    └──────────────── supervisord keeps nginx + uvicorn + node alive ──────────┘
```

The browser only ever calls same-origin `/api/*`; nothing in the frontend
knows a backend hostname. Server-side Nuxt (SSR) reaches the API through
`NUXT_API_PROXY_TARGET=http://127.0.0.1:8000`.

| File | Purpose |
|------|---------|
| `Dockerfile` (repo root) | Multi-stage build. Targets: `frontend-build`, `frontend`, `backend-build`, `backend`, **`app` (default, last)** |
| `deploy/nginx/nginx.conf` | In-container nginx on :8080, non-root friendly (pid/temp under `/tmp`, logs to stdout/stderr) |
| `deploy/supervisord.conf` | Runs nginx, uvicorn (`UVICORN_WORKERS`, default 2) and node; forwards logs to the container console |
| `docker-compose.yml` | Local stack: MongoDB + backend + frontend as separate containers |
| `.ebextensions/01-environment.config` | EB environment: single t3.small instance, `/api/health` health check, non-secret env |
| `.platform/nginx/conf.d/proxy.conf` | EB **host** nginx: 10m body limit, 300s timeouts, buffering off |
| `.ebignore` | What `eb deploy` bundles — **excludes `docker-compose.yml`** (see below) |
| `Procfile` | Same two processes for the non-Docker route (EB Python platform / honcho); ignored by the Docker platform |

## Production image locally

```bash
# from the repo root — builds the default (last) stage `app`
docker build -t menu-hero-core .

# APP_ENV=production is baked in, so SECRET_KEY is mandatory
docker run --rm -p 8080:8080 -e SECRET_KEY=change-me menu-hero-core

curl http://localhost:8080/api/health        # {"status":"ok"}
open http://localhost:8080                   # Nuxt app; /agent talks to the API
```

Useful overrides: `-e UVICORN_WORKERS=4`, `-e LOG_LEVEL=DEBUG`,
`-e DATABASE_URL=mongodb://...`, `-e LLM_PROVIDER=... -e LLM_API_KEY=...`.

Intermediate targets are buildable on their own:

```bash
docker build --target backend  -t menu-hero-backend  .   # uvicorn on :8000
docker build --target frontend -t menu-hero-frontend .   # nitro on :3000
```

Inside a running `app` container: `docker exec <id> supervisorctl status`.
On an Apple Silicon host the local image is arm64; that is fine locally, and
irrelevant for EB because EB builds the image on the (x86_64) instance itself.

## docker compose (development)

```bash
cp .env.example .env            # optional; LLM_API_KEY / LLM_PROVIDER / SECRET_KEY are picked up
docker compose up --build       # mongo :27017, backend :8000, frontend :3000
docker compose logs -f backend
docker compose down -v          # -v also drops the mongodata volume
```

`backend` gets `DATABASE_URL=mongodb://mongo:27017/menuhero` — the `mongo`
service runs without credentials on purpose, since the stack is local-only;
enabling auth means adding `?authSource=admin` to that URL as well —
and `APP_ENV=development`; `frontend` proxies `/api/*` to `http://backend:8000`
through its Nitro server route, so `http://localhost:3000` is again a single origin.

## Elastic Beanstalk (Docker on 64bit Amazon Linux 2023)

Prerequisites: AWS credentials configured, EB CLI 3.x (`pip install awsebcli`).

```bash
# 1. one-time: pick the Docker platform and region (creates .elasticbeanstalk/config.yml)
eb init -p docker -r us-east-1 menu-hero-core

# 2. create a single-instance environment (no load balancer)
eb create --single --instance-types t3.small menu-hero-prod

# 3. secrets — never commit these; .ebextensions only carries non-secret values
eb setenv SECRET_KEY='<long random string>' \
          DATABASE_URL='mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/menuhero' \
          LLM_API_KEY='<provider key>' \
          CORS_ORIGINS='https://your-domain.example'

# 4. every subsequent release
eb deploy
eb open                          # browser -> http://<env>.<region>.elasticbeanstalk.com
eb status && eb health           # enhanced health, /api/health is the check URL
eb logs                          # nginx + docker logs; `eb logs --all` for the full bundle
```

What happens on `eb deploy`:

1. The EB CLI zips the working directory filtered by `.ebignore`
   (uncommitted changes are included; `docker-compose.yml`, `node_modules`,
   `.venv`, `.output`, `.env`, caches are not).
2. On the instance EB runs `docker build` against the root `Dockerfile`
   (default target `app`), then `docker run` with the environment properties
   injected and the container's `EXPOSE 8080` published.
3. The host nginx (configured by EB, extended by `.platform/nginx/conf.d/proxy.conf`)
   proxies port 80 to the container's 8080. Inside, `deploy/nginx/nginx.conf`
   routes `/api/` to uvicorn and everything else to Nitro.
4. Health: Docker `HEALTHCHECK` on `/api/health` in the container; EB enhanced
   health with `Application Healthcheck URL: /api/health`.

**Why `.ebignore` excludes `docker-compose.yml`:** if a compose file is present
in the bundle, EB switches to *Docker Compose* mode — it runs `docker compose up`
and stops managing its host nginx, which breaks the port 80 → 8080 proxy above.

Timeouts: the image is built on the instance (npm ci + nuxt build + uv sync),
so `.ebextensions` raises the deployment command timeout to 30 minutes.
Non-secret env defaults (`APP_ENV`, `LOG_LEVEL`, `LLM_PROVIDER`,
`CORS_ORIGINS`) live in `.ebextensions/01-environment.config`; `eb setenv` and
console changes override them.

### HTTPS

A single-instance environment has no load balancer, so there are two options:

- **Load balancer (recommended):** create the environment without `--single`
  (or set `EnvironmentType: LoadBalanced`), request a certificate in ACM, and
  attach it to the 443 listener (`aws:elbv2:listener:443` →
  `Protocol: HTTPS`, `SSLCertificateArns: arn:aws:acm:...`). TLS terminates at
  the ALB; the container receives `X-Forwarded-Proto: https`, which both nginx
  layers pass through untouched.
- **Certbot on the instance:** keep single-instance and terminate TLS in the
  host nginx with a `.platform/hooks/postdeploy` script that runs certbot for
  your domain. Cheaper, but the certificate lives on one box and renewals are
  your job.

### Database (MongoDB)

Do not put data you want to keep in a database Elastic Beanstalk creates for
the environment — EB deletes such a resource together with the environment.
Provision the database on its own and point the environment at it.

**MongoDB Atlas (recommended).** Create a cluster, add the environment's
public IP — or the NAT gateway / VPC-peering CIDR the instance egresses
through — to the Atlas IP access list, then set the connection string:

```bash
eb setenv DATABASE_URL='mongodb+srv://menuhero:<password>@cluster0.xxxxx.mongodb.net/menuhero?retryWrites=true&w=majority'
```

`mongodb+srv://` finds the cluster's hosts over DNS SRV records, which needs
dnspython — the `pymongo[srv]` extra in `backend/pyproject.toml` already pulls
it in. Such a URL must **not** carry a port number: pymongo rejects one, and
the backend rejects it earlier, while the settings load.

**Amazon DocumentDB (in-VPC alternative, extra work).** Put the cluster in the
environment's VPC and let its security group accept port 27017 from the EB
instance's security group. TLS is on by default, so the Amazon RDS CA bundle
(`global-bundle.pem`) has to be added to the image — the Dockerfile does not
fetch it today — and referenced from the URL:
`mongodb://menuhero:<password>@<docdb-endpoint>:27017/menuhero?tls=true&tlsCAFile=/path/to/global-bundle.pem`.
DocumentDB is MongoDB-API-compatible rather than MongoDB, so behaviour can
differ; this is not the default path.

**Self-hosted MongoDB on the instance** is not recommended: one unreplicated
node with no backups, and the data disappears with the environment.

`DATABASE_URL` is optional: the backend runs without a database — nothing
connects at start-up, and the routes that depend on one answer 503
`Database is not configured`. When it is set it must be a MongoDB connection
string (`mongodb://` or `mongodb+srv://`); any other scheme is rejected as the
settings load, so a leftover `postgresql+asyncpg://` value now stops the
process instead of being ignored. `MONGODB_DATABASE` (default `menuhero`)
supplies the database name for URLs that carry no path.

### Troubleshooting

- `eb logs` — host nginx (`/var/log/nginx/*`) and container stdout
  (`/var/log/eb-docker/containers/eb-current-app/*`), which is where
  supervisord forwards nginx, uvicorn and node output.
- `eb ssh`, then `sudo docker ps`, `sudo docker logs <id>`,
  `sudo docker exec <id> supervisorctl status`.
- A failed deploy usually means the build failed: look for `npm ci` /
  `nuxt build` / `uv sync` errors in `eb logs --all` (`eb-engine.log`).
