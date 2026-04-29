#!/bin/sh
# Nirogidhara backend container entrypoint.
#
# Behaviour by role (selected via the compose service `command`):
#   - daphne ...                 → wait for DB, run migrate + collectstatic,
#                                  then exec Daphne. (Default if no command
#                                  is supplied — fixes the historical
#                                  "parameter not set" crash on backend.)
#   - python ...                 → same as daphne (one-off `manage.py` runs
#                                  benefit from migrate having happened).
#   - celery -A config worker    → wait for DB + Redis, then exec Celery.
#   - celery -A config beat      → wait for DB + Redis, then exec Celery beat.
#
# Hard rules:
#   - never bake secrets; everything comes from env supplied by
#     docker-compose.prod.yml + .env.production.
#   - Worker / beat must skip migrate (the backend container owns schema).
#   - `set -e` only — `set -u` was historically unsafe here because some
#     compose service commands omitted positional args entirely.
set -e

echo "[entrypoint] Starting Nirogidhara backend..."

# --- Default command ------------------------------------------------------
# Compose's backend service intentionally relies on the Dockerfile CMD,
# which means tini may invoke the entrypoint with zero positional args
# in some Docker runtimes. Default to Daphne so a no-args invocation
# still serves traffic instead of crashing.
if [ "$#" -eq 0 ]; then
    set -- daphne -b 0.0.0.0 -p 8000 config.asgi:application
fi

ROLE="other"
case "$1" in
    daphne|python)
        ROLE="backend"
        ;;
    celery)
        # Detect worker vs. beat from the next arg.
        if [ "${2:-}" = "beat" ]; then
            ROLE="beat"
        else
            ROLE="worker"
        fi
        ;;
esac

echo "[entrypoint] role=$ROLE pid=$$"

# --- Wait for Postgres ----------------------------------------------------
# Bounded retries: 30 attempts × 2s ≈ 1 minute. If Postgres still isn't
# reachable the entrypoint exits non-zero so the orchestrator restarts us.
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
    echo "[entrypoint] waiting for database..."
    python - <<'PY' || exit 1
import os, sys, time, socket
import dj_database_url

cfg = dj_database_url.parse(os.environ["DATABASE_URL"])
host = cfg.get("HOST") or "localhost"
port = int(cfg.get("PORT") or 5432)

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
    echo "[entrypoint] waiting for redis..."
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

# --- Backend / management bootstrap --------------------------------------
# Worker + beat skip migrate / collectstatic — the backend container owns
# schema and static collection.
if [ "$ROLE" = "backend" ]; then
    echo "[entrypoint] Running database migrations..."
    python manage.py migrate --no-input

    echo "[entrypoint] Collecting static files..."
    python manage.py collectstatic --no-input || \
        echo "[entrypoint] collectstatic failed (non-fatal)."
fi

echo "[entrypoint] Executing: $*"
exec "$@"
