# Nirogidhara AI Command Center — backend image (Phase 5B-Deploy).
#
# Single image is reused by three services in `docker-compose.prod.yml`:
#   - nirogidhara-backend  (Daphne ASGI on :8000)
#   - nirogidhara-worker   (Celery worker)
#   - nirogidhara-beat     (Celery beat)
#
# The container command is supplied by compose, NOT baked here.
#
# Hard rules (Master Blueprint §26):
#  - Never bake secrets. All env comes from `.env.production` at runtime.
#  - Migrations + collectstatic happen in the entrypoint, not the build.
#  - Image runs as a non-root user.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings

# System deps:
#  - libpq5 + build-essential are needed for psycopg[binary] wheels on slim.
#  - tini gives Daphne / Celery clean signal handling under PID 1.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        tini \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY . /app/

# Non-root runtime user (the postgres / redis volumes mount as their own
# uids; only /app + STATIC_ROOT need to be writable here).
RUN useradd --create-home --uid 10001 nirogidhara \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R nirogidhara:nirogidhara /app /home/nirogidhara

USER nirogidhara

# Daphne listens here in the backend service; worker + beat ignore it.
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--", "/app/deploy/backend/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
