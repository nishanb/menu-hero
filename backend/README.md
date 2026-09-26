# Menu Hero backend (`menu-hero-backend`)

FastAPI application serving the `/api/*` endpoints of Menu Hero. Import root: `app`.
It depends on the sibling [`agents`](../agents) package (editable path dependency) for all
agent logic and never contains any itself.

## Run

```bash
cd backend
uv sync                                   # creates backend/.venv (Python 3.13, see .python-version)
uv run uvicorn app.main:app --reload --port 8000
# or, without uv on PATH:
.venv/bin/uvicorn app.main:app --port 8000
```

Then:

```bash
curl -s http://127.0.0.1:8000/api/health
# {"status":"ok"}
curl -s http://127.0.0.1:8000/api/agents
# {"agents":[{"name":"example","description":"..."},{"name":"example_workflow","description":"..."}]}
curl -s -X POST http://127.0.0.1:8000/api/agents/run \
  -H 'content-type: application/json' -d '{"message":"Hello agent"}'
# {"response":"Processed: Hello agent","agent":"example","metadata":{"tools_used":["word_count"],...}}
curl -s -N -X POST http://127.0.0.1:8000/api/agents/stream \
  -H 'content-type: application/json' -d '{"message":"hi"}'
# event: agent_started / tool_started / tool_completed / agent_completed (SSE)
```

Interactive docs: **http://127.0.0.1:8000/api/docs** (ReDoc at `/api/redoc`, schema at
`/api/openapi.json`). They live under the `/api` prefix on purpose: in production nginx
routes only `/api/` to this process, everything else goes to the Nuxt frontend.

Or with live reload inside Docker, alongside MongoDB and the front end (see the root
README for what the overlay changes):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
docker compose exec -e TEST_MONGODB_URL=mongodb://mongo:27017 backend pytest -q
```

## Test and lint

```bash
cd backend
uv run pytest -q
uv run ruff format --check .   # `uv run ruff format .` to fix
uv run ruff check .
uv run mypy .
```

`pytest` runs with `APP_ENV=test` and with `Settings`' `env_file` disabled (see
`tests/conftest.py`), so the repo-root `.env` cannot change an outcome — the environment
the fixtures set is the only input. It uses the real `agents` package through the
in-process executor. Nothing talks to the network — Google is replaced
by the `FakeGoogleProvider` double in `tests/conftest.py`, which still runs the real
`id_token` claim validation. The repository tests and the whole auth/management suite
(`tests/test_models.py`, `tests/test_auth_flow.py`, `tests/test_management_api.py`) need a
real MongoDB and skip themselves when none is reachable, so a laptop without one still gets
a green suite; start one to run all 139:

```bash
docker run --rm -d -p 27017:27017 --name mh-mongo mongo:8
uv run pytest -q
docker rm -f mh-mongo
```

## Configuration

Settings are read by `app/core/config.py` (pydantic-settings) from environment variables,
falling back to the repo-root `.env` and then `./.env`; real env vars win. Copy the
repo-root `.env.example` to `.env` to get started.

| Variable | Default | Notes |
|----------|---------|-------|
| `APP_ENV` | `development` | `development` / `test` / `production` |
| `SECRET_KEY` | *(empty)* | **Required when `APP_ENV=production`** (startup fails otherwise) |
| `DATABASE_URL` | *(unset)* | MongoDB connection string: `mongodb://user:pw@host:27017/menuhero` or `mongodb+srv://user:pw@cluster0.xxxxx.mongodb.net/menuhero`. Optional: nothing connects at startup, DB routes answer 503 when unset |
| `MONGODB_DATABASE` | `menuhero` | Database name, used when `DATABASE_URL` carries no path (a path in the URL wins) |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated list or a JSON list |
| `LOG_LEVEL` | `INFO` | Standard logging level name |
| `GOOGLE_CLIENT_ID` | *(empty)* | OAuth 2.0 **web application** client id; `/api/v1/auth/google` answers 503 while unset |
| `GOOGLE_CLIENT_SECRET` | *(empty)* | Its secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:3000/api/v1/auth/google/callback` | Must be registered verbatim in the Google console, and **share a hostname with `FRONTEND_BASE_URL`** |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Origin the sign-in callback redirects back to |
| `SESSION_COOKIE_NAME` | `mh_session` | Name of the session cookie |
| `SESSION_TTL_DAYS` | `30` | Session (and cookie) lifetime |
| `INVITE_TTL_DAYS` | `14` | How long an invite stays pending |
| `BOOTSTRAP_ADMIN_EMAILS` | *(empty)* | Comma-separated addresses that sign in as platform `admin` — the only way to create the first one |

`DATABASE_URL` is a `str` validated by hand (a MongoDB scheme, a host, and no port on
`mongodb+srv://`) rather than a pydantic `MongoDsn`: pydantic normalises a URL by adding the
default port, and pymongo rejects a `mongodb+srv://` URI that carries one ("must not include
a port number"), which would break every MongoDB Atlas deployment. The operator's string
therefore reaches the driver verbatim and the driver owns the rest of it; `redact_credentials()`
in `app/core/database.py` is what makes it safe to log.

`LLM_*` and `AGENT_TIMEOUT_SECONDS` belong to the `agents` package and are read from the
same `.env` by `agents.get_settings()`; the backend never handles them.

## Request path

```
HTTP request
  │
  ▼
app/api/routes/agents.py          FastAPI route: validates AgentRequest, no agent logic
  │   Depends(get_agent_service)  app/dependencies/agents.py
  ▼
app/services/agent_service.py     AgentService: HTTP schema -> agents.AgentRequest, logging
  │
  ▼
AgentExecutor (Protocol)          InProcessAgentExecutor today; QueuedAgentExecutor tomorrow
  │                               (publishes a job, awaits the result from a worker that
  │                                calls the same agents.run_agent())
  ▼
agents.run_agent() / agents.stream_agent()     registry lookup, timeout, error wrapping
  │
  ▼
agents.ExampleAgent.run()  ->  agents.AgentResult  ->  AgentResponse (JSON)
                               agents.AgentEvent   ->  SSE message (stream endpoint)
```

## HTTP API (prefix `/api`)

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/health` | `{"status": "ok"}` |
| GET | `/api/agents` | `{"agents": [{"name", "description"}, ...]}` |
| POST | `/api/agents/run` | `{"response", "agent", "metadata"}` |
| POST | `/api/agents/stream` | `text/event-stream`, one `event: <type>\ndata: <event JSON>\n\n` per agent event |

Request body for `run` and `stream`: `{"message": str (1..10000 chars), "agent": str = "example"}`.

### Management app (prefix `/api/v1`)

Google sign-in, sessions and role management. `/api/health` and `/api/agents` predate the
versioned surface and stay unversioned; everything new lands under `/api/v1`.

| Method | Path | Who | Response |
|--------|------|-----|----------|
| GET | `/api/v1/auth/google` | anyone | 307 to Google's consent screen (`?next=/some/path` to come back to a specific page) |
| GET | `/api/v1/auth/google/callback` | Google | 302 to `FRONTEND_BASE_URL` + the portal, with the session cookie set; failures go to `/login?error=<code>` |
| GET | `/api/v1/auth/me` | signed in | `{"user", "effective_role", "portal_path", "memberships"}` |
| POST | `/api/v1/auth/logout` | anyone | `{"signed_out": bool}`; revokes the session document and clears the cookie |
| POST | `/api/v1/auth/invites/accept` | signed in | The `/auth/me` body, after joining the restaurant the token names |
| POST | `/api/v1/tenants` | admin | The created restaurant (201) |
| GET | `/api/v1/tenants` | signed in | The caller's restaurants (all of them for an admin) |
| GET | `/api/v1/tenants/{id}` | member | One restaurant |
| GET | `/api/v1/tenants/{id}/members` | member | The team, with the person behind each membership |
| PATCH | `/api/v1/tenants/{id}/members/{user_id}` | owner | The updated membership |
| DELETE | `/api/v1/tenants/{id}/members/{user_id}` | owner | 204 |
| POST | `/api/v1/tenants/{id}/invites` | owner | `{"invite", "token", "accept_url"}` (201) — the token is shown once |
| GET | `/api/v1/tenants/{id}/invites` | owner | Pending invites |
| DELETE | `/api/v1/tenants/{id}/invites/{invite_id}` | owner | 204 |
| GET | `/api/v1/users` | admin | Everyone who has signed in |
| PATCH | `/api/v1/users/{user_id}/role` | admin | The updated user |

A platform `admin` passes every "owner" check as well.

### Roles

Roles live at two scopes, which is what lets someone sign in before they belong to any
restaurant, and lets one person be an owner here and staff there:

| Role | Scope | Stored in | Granted by |
|------|-------|-----------|------------|
| `admin` | platform | `users.platform_role` | another admin, or `BOOTSTRAP_ADMIN_EMAILS` |
| `user` | platform | `users.platform_role` | **the default for every new sign-in** |
| `owner` | one restaurant | `memberships.role` | an admin at tenant creation, or an owner |
| `staff` | one restaurant | `memberships.role` | an owner, through an invite |

`GET /api/v1/auth/me` reports the strongest role held (`admin` > `owner` > `staff` >
`user`) and the `portal_path` the frontend should route to (`/admin`, `/owner`, `/staff`,
`/app`). Two invariants are enforced in `app/services/management_service.py`: an admin
cannot change their own platform role, and a restaurant always keeps at least one owner.

### Sign-in and sessions

```
GET /api/v1/auth/google ──307──▶ Google ──▶ GET /api/v1/auth/google/callback
     sets mh_oauth_state                        verifies state, exchanges the code,
     (HttpOnly, 10 min)                         upserts the user, consumes any invite
                                                for that verified email, opens a session
                                                ──302──▶ FRONTEND_BASE_URL + /admin|/owner|/staff|/app
```

The callback is registered on the **frontend** origin, not the backend's: Nuxt proxies
`/api/*` through to FastAPI (`frontend/server/api/[...].ts`), so the `Set-Cookie` comes back
on the host the app is served from. Cookies are scoped by host and ignore the port, so a
callback on `127.0.0.1:8000` would set a cookie the page on `localhost:3000` never sends
back and the sign-in would look like an endless loop — pick one hostname and use it in
`GOOGLE_REDIRECT_URI`, `FRONTEND_BASE_URL` and the browser. Start-up logs a warning when
the two disagree.

The session cookie carries an **opaque token**, not a signed claim set: only its SHA-256
digest is stored, and the session document holds nothing but `user_id`. Roles are therefore
read from the database on every request, so a role change or a logout is in force on the
caller's next request rather than whenever a month-long token would have expired. The
cookie is `HttpOnly`, `SameSite=Lax` (the callback is a top-level navigation, which a
`Strict` cookie would not be sent on) and `Secure` when `APP_ENV=production`.

The `id_token` is verified, not merely decoded: **joserfc** checks its signature against
Google's published JWKS (keys cached for an hour, refetched once on a verification failure
so a key rotation cannot lock everyone out) with the permitted algorithms pinned to RS256
and ES256, and validates `iss`, `aud`, `exp` and `sub` through a claims registry.
`email_verified` is checked on top as application policy. The authorization URL is built by
**authlib**'s `OAuth2Client`. `tests/test_google_oauth.py` signs tokens with generated keys
and asserts that a forged signature, a tampered payload and an HS256 token are all refused.

Identity is keyed on the Google subject alone. A different Google account presenting an
email that is already registered is refused (`/login?error=account_conflict`) rather than
re-bound onto the existing user. A `BOOTSTRAP_ADMIN_EMAILS` address is the exception to the
role rules: it is promoted to `admin` at *every* sign-in, so demoting one through the API
does not survive their next login — revoke it by removing the address from the environment.

Invites are pending *memberships*, not credentials: `POST /api/v1/tenants/{id}/invites`
returns a one-time token, and the membership is created only when someone signs in with a
Google account whose **verified** email matches — so a leaked link grants nothing to
whoever opens it. Nothing is emailed in v1; the response carries the link for the UI to
send.

Error mapping (`app/main.py` exception handlers, tracebacks are logged and never returned):

| Exception (from `agents`) | Status | Body |
|---------------------------|--------|------|
| `AgentNotFoundError` | 404 | `{"detail": "Unknown agent '<name>'"}` |
| `AgentTimeoutError` | 504 | `{"detail": "Agent timed out"}` |
| any other `AgentError` | 500 | `{"detail": "Agent execution failed"}` |
| request validation | 422 | FastAPI default |

The stream endpoint answers 404 for an unknown agent before the stream starts. A failure
*during* a run is delivered as the agent's own `agent_failed` event; an error raised by the
pipeline after the response started (for example the run deadline, `AGENT_TIMEOUT_SECONDS`)
ends the stream with `event: error` and the same `detail` strings as above.

## Layout

```
backend/
├── pyproject.toml            deps, ruff/mypy/pytest config, uv source for ../agents
├── .python-version           3.13
├── app/
│   ├── main.py               create_app() + module-level `app`; lifespan; exception handlers
│   ├── api/router.py         aggregates route modules; `/api` + the `/api/v1` sub-router
│   ├── api/routes/           health.py, agents.py (SSE), auth.py, tenants.py, users.py
│   ├── core/config.py        Settings, get_settings(), clear_settings_cache()
│   ├── core/logging.py       setup_logging(level) — root + uvicorn loggers, idempotent
│   ├── core/database.py      lazy AsyncMongoClient: get_client(), get_database(), ping(), close_client()
│   ├── core/security.py      opaque session/invite tokens: generate_token(), hash_token()
│   ├── models/base.py        PyObjectId, MongoDocument, MongoRepository[TDocument]
│   ├── models/               roles.py, user.py, tenant.py, membership.py, session.py, invite.py, indexes.py
│   ├── schemas/              health.py, agent.py, auth.py, management.py
│   ├── services/agent_service.py       AgentExecutor Protocol, InProcessAgentExecutor, AgentService
│   ├── services/google_oauth.py        GoogleIdentityProvider Protocol + the real client
│   ├── services/auth_service.py        sign-in, invites, sessions, AuthContext
│   ├── services/management_service.py  tenants, memberships, platform roles, invites
│   └── dependencies/         get_agent_service(), get_db() (`Db`), `CurrentUser`, `PlatformAdmin`
└── tests/                    conftest (APP_ENV=test, TestClient with lifespan) + suites
```

## Adding things

- **New agent**: implement it in `agents/` and register it in `agents.build_default_registry()`;
  it is immediately listed by `GET /api/agents` and runnable via `"agent": "<name>"`.
- **New endpoint**: add a route module under `app/api/routes/`, include it in
  `app/api/router.py`, keep logic in a service under `app/services/`.
- **Database collection**: define a `MongoDocument` and its `MongoRepository` (see
  [below](#adding-a-collection)), take the database handle with `db: Db`
  (`app/dependencies/database.py`), set `DATABASE_URL`, and add the repository to
  `REPOSITORIES` in `app/models/indexes.py` if it declares indexes.
- **Protected endpoint**: annotate the caller as `context: CurrentUser` (401 when signed
  out) or `admin: PlatformAdmin` (403 for anyone else) from `app/dependencies/auth.py`, and
  call `ManagementService.assert_member` / `assert_can_manage_tenant` for a tenant-scoped
  check.
- **Background execution**: implement the `AgentExecutor` Protocol (see the module docstring
  of `app/services/agent_service.py`) and swap it in `app/dependencies/agents.py`.

### Adding a collection

There is no schema to declare and nothing to migrate — a collection exists as soon as
something writes to it. Define the document and its repository together, keep every driver
call inside the repository, and let a service under `app/services/` call the repository:

```python
# app/models/recipe.py
from app.models import MongoDocument, MongoRepository


class Recipe(MongoDocument):  # `_id: PyObjectId | None` comes from MongoDocument
    name: str
    servings: int = 1


class RecipeRepository(MongoRepository[Recipe]):
    collection_name = "recipes"
    document_type = Recipe
    # override `ensure_indexes()` when the collection needs indexes
```

`MongoRepository` already gives every subclass `insert()`, `get()`, `find()`, `find_one()`,
`count()`, `update_by_id()`, `delete()`, `delete_many()` and `ensure_indexes()`; collection-specific queries become methods on the
subclass instead of `db["recipes"]` calls scattered through routes and services. A route
asks for the database handle and hands it to the repository:

```python
# app/api/routes/recipes.py
from fastapi import APIRouter

from app.dependencies.database import Db
from app.models.recipe import Recipe, RecipeRepository

router = APIRouter()


@router.get("/recipes")
async def list_recipes(db: Db) -> list[Recipe]:
    return await RecipeRepository(db).find(limit=50, sort=[("servings", -1)])
```

`Db` is `Annotated[MongoDatabase, Depends(get_db)]` — a database handle, not a session:
there is nothing to open, commit or close per request, and the dependency answers 503 when
`DATABASE_URL` is unset.

Repository tests run against a real MongoDB at `TEST_MONGODB_URL` (default
`mongodb://127.0.0.1:27017`) and skip themselves when none is reachable, which is why a
laptop without one still gets a green suite:

```bash
docker run --rm -d -p 27017:27017 --name mh-mongo mongo:8
TEST_MONGODB_URL=mongodb://127.0.0.1:27017 uv run pytest tests/test_models.py
docker rm -f mh-mongo
```

`docker compose up` (repo root) already runs the same `mongo:8` on 27017, so that stack
serves the tests just as well.
