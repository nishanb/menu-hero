# Menu Hero Core — process definitions for the NON-Docker path.
#
# Mirrors deploy/supervisord.conf (same commands, same loopback ports) for an
# Elastic Beanstalk *Python platform* environment or a local `honcho start`,
# after `cd backend && uv sync` and `cd frontend && npm ci && npm run build`.
# A reverse proxy (deploy/nginx/nginx.conf, or EB's host nginx, which targets
# 127.0.0.1:8000 on the Python platform) must front these to serve one origin.
#
# Elastic Beanstalk's DOCKER platform ignores this file: the Dockerfile's
# supervisord starts the same processes inside the container.
web: cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
frontend: cd frontend && node .output/server/index.mjs
