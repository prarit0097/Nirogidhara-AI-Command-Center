#!/usr/bin/env sh
# Nirogidhara backend container entrypoint.
#
# Behaviour by role (selected via the compose service `command`):
#   - `daphne ...` (default)   → wait for DB, run migrate + collectstatic,
#                                 then exec Daphne.
#   - `celery -A config worker` → wait for DB + Redis, then exec Celery.
#   - `celery -A config beat`   → wait for DB + Redis, then exec Celery beat.
#
# The script never bakes secrets; everything comes from env supplied by
# docker-compose.prod.yml + .env.production.
set -eu

ROLE="backend"
case "$1" in
    celery)
        # Detect worker vs. beat from $2.
        if [ "${2:-}" = "beat" ]; then
            ROLE="beat"
        else
            ROLE="worker"
        fi
        ;;
esac

echo "[entrypoint] role=$ROLE pid=$$"

# ---- Wait for Postgres -------------------------------------------------
# We never block forever — 30 attempts × 2s = 1 minute. If Postgres still
# isn't reachable, fail closed so the orchestrator restarts us.
wait_for_db() {
    if [ -z "${DATABASE_URL:-}" ]; then
        echo "[entrypoint] DATABASE_URL not set; skipping DB wait."
        return 0
    fi
    case "$DATABASE_URL" in
        sqlite*)
            echo "[entrypoint] sqlite — no remote wait needed."
            return 0
            ;;
    esac
    echo "[entrypoint] waiting for database…"
    python - <<'PY' || exit 1
import os, sys, time
import dj_database_url

cfg = dj_database_url.parse(os.environ["DATABASE_URL"])
host = cfg.get("HOST") or "localhost"
port = int(cfg.get("PORT") or 5432)

import socket
for attempt in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] db reachable at {host}:{port}")
            sys.exit(0)
    except OSError as exc:
        print(f"[entrypoint] db not ready (attempt {attempt+1}/30): {exc}")
        time.sleep(2)
sys.exit(1)
PY
}

wait_for_redis() {
    if [ -z "${CELERY_BROKER_URL:-}" ]; then
        return 0
    fi
    case "$CELERY_BROKER_URL" in
        redis://*) ;;
        *) return 0 ;;
    esac
    echo "[entrypoint] waiting for redis…"
    python - <<'PY' || exit 1
import os, sys, socket, time
from urllib.parse import urlparse

url = urlparse(os.environ.get("CELERY_BROKER_URL", ""))
host = url.hostname or "localhost"
port = url.port or 6379

for attempt in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] redis reachable at {host}:{port}")
            sys.exit(0)
    except OSError as exc:
        print(f"[entrypoint] redis not ready (attempt {attempt+1}/30): {exc}")
        time.sleep(2)
sys.exit(1)
PY
}

wait_for_db
wait_for_redis

# ---- Backend-only bootstrap ---------------------------------------------
# Worker + beat do not run migrate; the backend container owns schema.
if [ "$ROLE" = "backend" ]; then
    echo "[entrypoint] running migrations…"
    python manage.py migrate --noinput

    echo "[entrypoint] collectstatic…"
    python manage.py collectstatic --noinput || \
        echo "[entrypoint] collectstatic failed (non-fatal)."
fi

echo "[entrypoint] exec: $*"
exec "$@"
