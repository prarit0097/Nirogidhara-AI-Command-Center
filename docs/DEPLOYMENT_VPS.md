# Deploying Nirogidhara AI Command Center to Hostinger VPS

> Target domain: **`ai.nirogidhara.com`**
> App folder on VPS: **`/opt/nirogidhara-command`**
> Stack: isolated Postgres + Redis + Daphne backend + Celery worker + Celery beat + Nginx (Vite SPA)
> Compose project name: **`nirogidhara-command`**

This runbook is the authoritative production deploy path. Every command
below runs on the VPS unless explicitly marked _(local)_. Local dev keeps
using `python manage.py runserver` + `npm run dev` — Docker is **production
only**.

---

## 0. Why this stack

| Need | Choice | Why |
| --- | --- | --- |
| HTTP + WebSockets in one process | Daphne ASGI | Phase 4A `/ws/audit/events/` requires Channels. Gunicorn alone would not work. |
| Background tasks + cron | Celery worker + beat | Phase 3C scheduler + Phase 5A retry/backoff/jitter on WhatsApp sends. |
| Database | Postgres 16 (container) | SQLite is dev only. Postgres handles concurrent webhooks (Razorpay / Delhivery / Vapi / Meta / WhatsApp). |
| Cache + broker + Channels layer | Redis 7 (container) | Three indices (0/1/2) used by Celery broker / Celery results / Channels group fan-out. |
| Static assets + reverse proxy | Nginx (container) with built Vite SPA | Single host port (18020) serves the SPA + proxies API/WS/admin to the backend container. |
| Host-port isolation | **18020 → 80** | Existing Postzyo / OpenClaw containers already use other host ports. 18020 is free. The host Nginx / Hostinger Traefik then proxies `ai.nirogidhara.com → 127.0.0.1:18020`. |

---

## 1. Prerequisites on the VPS

```bash
# Already present from Postzyo / OpenClaw — just verify.
docker --version          # >= 24
docker compose version    # v2 plugin
git --version             # any
```

If Docker is missing, install via Docker's official `get.docker.com`
script. **Do not** add this user to the `docker` group on a shared VPS
without confirming with the team — the existing setup may already use
`sudo docker`.

---

## 2. Initial setup (one-time)

```bash
# Clone into the production folder.
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/prarit0097/Nirogidhara-AI-Command-Center.git nirogidhara-command
cd /opt/nirogidhara-command

# Stamp the production env file from the example.
sudo cp .env.production.example .env.production
sudo chmod 600 .env.production
sudo nano .env.production
```

Inside `.env.production`, fill in at minimum:

- `DJANGO_SECRET_KEY` — `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `JWT_SIGNING_KEY` — different long random string
- `POSTGRES_PASSWORD` — strong; reflect the same string into `DATABASE_URL`
- `DJANGO_ALLOWED_HOSTS` — `ai.nirogidhara.com,localhost,127.0.0.1`
- `CORS_ALLOWED_ORIGINS` — `https://ai.nirogidhara.com`
- `CSRF_TRUSTED_ORIGINS` — `https://ai.nirogidhara.com`

Leave `WHATSAPP_PROVIDER=mock`, `RAZORPAY_MODE=mock`, `DELHIVERY_MODE=mock`,
`VAPI_MODE=mock`, `META_MODE=mock`, `AI_PROVIDER=disabled` until the
production credentials for each are confirmed by Prarit. Switching them
to live before keys are valid will fail closed (the adapters refuse to
load), but configuring them prematurely with the wrong values risks
sending a customer message during a smoke test — keep them mocked.

> **Never commit `.env.production`.** It is gitignored at the repo root.

---

## 3. First boot

```bash
cd /opt/nirogidhara-command
sudo docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Compose builds two images (`nirogidhara/backend`, `nirogidhara/nginx`)
and starts six containers:

```
nirogidhara-db          postgres:16-alpine        internal-only
nirogidhara-redis       redis:7-alpine            internal-only
nirogidhara-backend     custom (Daphne :8000)     internal-only
nirogidhara-worker      custom (celery worker)    internal-only
nirogidhara-beat        custom (celery beat)      internal-only
nirogidhara-nginx       custom (vite + nginx)     127.0.0.1:18020 → 80
```

Wait ~60 seconds for the healthchecks, then verify:

```bash
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
```

Expected output: `db reachable at postgres:5432 → redis reachable at redis:6379 → migrate → collectstatic → daphne listening on 0.0.0.0:8000`.

---

## 4. Migrate + create superuser

The backend entrypoint already runs `migrate` on every restart, but the
first boot may not have a Django admin user. Create one:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py createsuperuser
```

After **every** `git pull` on the VPS, run the migration drift gate so
schema drift is caught at deploy time, not at the next dev session:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py migrate
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py makemigrations --check --dry-run

# Phase 5E-Hotfix-2 — refresh demo Claim Vault rows to demo-v2 once.
# Real admin / doctor-approved claims are NEVER overwritten.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_default_claims --reset-demo

# Confirm no demo row is reported as weak.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py check_claim_vault_coverage

# Phase 5E-Smoke — controlled smoke harness. Defaults are SAFE
# (dry-run + mock-WhatsApp + mock-Vapi + OpenAI off). Run before
# flipping any automation flag. Refuses real Meta provider outright.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario all --json

# Phase 5E-Smoke-Fix-2 — adapter code change. Modern OpenAI Chat
# models (gpt-4o, gpt-5, o1, o3, …) reject 'max_tokens' and require
# 'max_completion_tokens'. The adapter now always uses the modern
# parameter. After this commit, rebuild + restart so the new adapter
# code lands in the backend image, then re-run the OpenAI smoke.

# Phase 5E-Smoke-Fix — when the requirements.txt changes (e.g. the
# openai SDK was added), rebuild the backend image so pip install
# picks up the new dep, then re-run the OpenAI provider smoke. The
# expected outcome is openaiSucceeded=true + providerPassed=true.
# A safeFailure=true result means the SDK / API key / AI_PROVIDER
# is wrong — fix it before flipping any automation flag.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production build backend
sudo docker compose -f docker-compose.prod.yml --env-file .env.production up -d backend worker beat
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python -c "from openai import OpenAI; print('openai SDK OK')"
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test \
        --scenario ai-reply --language hinglish --use-openai --mock-whatsapp --dry-run --json

# Single-scenario examples (use these to debug a specific surface).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario claim-vault --json

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hinglish --mock-whatsapp --dry-run

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario rescue-discount --dry-run --json

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario vapi-handoff --mock-vapi --dry-run

sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py run_controlled_ai_smoke_test --scenario reorder-day20 --dry-run
```

Expected output: `No changes detected`. If the `--check` reports
pending migrations, **stop the deploy** — a hand-rolled migration
drifted from the model definition. Generate the missing migration
locally with `python manage.py makemigrations`, push the new
`apps/<app>/migrations/0XXX_*.py` file, then re-pull on the VPS.

Phase 5E-Hotfix is the canonical example of this drift: Phase 5D / 5E
shipped with hand-rolled short index names (`whatsapp_wh_convers_h0_idx`,
`orders_disc_order_i_dol_idx`, …) that did not match Django's auto-suffix
form, and the VPS first-deploy after commit `8374863` reported pending
migrations until two `RenameIndex` migrations (`0004_rename_*`) were
generated locally and re-pulled.

Optional demo seed (do **not** run on a live customer DB):

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py seed_demo_data --reset
```

Sync the canonical lifecycle WhatsApp templates so the `/whatsapp-templates`
page has working rows:

```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec backend python manage.py sync_whatsapp_templates
```

---

## 5. Smoke tests

```bash
# Backend health (DRF)
curl -fsS http://127.0.0.1:18020/api/healthz/
# {"status":"ok","service":"nirogidhara-backend"}

# Frontend SPA root
curl -fsSI http://127.0.0.1:18020/

# WebSocket route exists (will 426 / 400 without a proper Upgrade header)
curl -fsSI http://127.0.0.1:18020/ws/audit/events/ | head -1
```

Browser tour (after the host Nginx / Traefik step in §6):

- `https://ai.nirogidhara.com/` — Command Center dashboard
- `https://ai.nirogidhara.com/whatsapp-inbox` — Phase 5B inbox (manual-only)
- `https://ai.nirogidhara.com/admin/` — Django admin (login with the superuser above)

---

## 6. DNS + TLS for `ai.nirogidhara.com`

### 6.1 DNS

Add an A record at the registrar:

```
Type:  A
Host:  ai
Value: <Hostinger VPS public IP>     # e.g. 187.127.132.106
TTL:   300
```

Wait for propagation (`dig +short ai.nirogidhara.com`) before requesting
a TLS cert.

### 6.2 Option A — Host-level Nginx + Certbot (recommended)

This is the cleanest path on a Hostinger VPS that already runs other
Docker projects. Each project keeps its own internal Nginx and exposes
one host port; the host Nginx terminates TLS and routes by domain.

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

sudo tee /etc/nginx/sites-available/ai.nirogidhara.com >/dev/null <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name ai.nirogidhara.com;

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:18020;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/ai.nirogidhara.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Auto-issues + auto-renews. Pick redirect-to-HTTPS when prompted.
sudo certbot --nginx -d ai.nirogidhara.com
```

After certbot completes, browse to `https://ai.nirogidhara.com/`.

### 6.3 Option B — Hostinger Traefik / Docker Manager

If the VPS is managed entirely through Hostinger's Docker UI, point the
`ai.nirogidhara.com` route at this project's container port `80` (the
inner Nginx). Hostinger's Traefik handles TLS via Let's Encrypt
automatically. The container's host port (`18020`) is unchanged so it
stays compatible with the host-Nginx fallback above.

> Pick **one** of A or B — running both at the same time leaks the same
> upstream behind two domains and confuses CSRF / consent telemetry.

---

## 7. Daily operations

### 7.1 Logs

```bash
cd /opt/nirogidhara-command
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f beat
sudo docker compose -f docker-compose.prod.yml --env-file .env.production logs -f nginx
```

### 7.2 Restart / stop

```bash
# Restart everything (keeps volumes + data).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production restart

# Stop the stack (keeps volumes + data).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production down

# Stop + delete volumes (DANGER — wipes DB + Redis state).
# Only on explicit user confirmation.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production down -v
```

### 7.3 Update deployment

```bash
cd /opt/nirogidhara-command
sudo git pull origin main

# Rebuild + restart. `--pull never` keeps the local image cache in
# place; without it Compose tries to pull `nirogidhara/backend:latest`
# from a registry that does not exist and the deploy stalls.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never

# Run migrations explicitly (the entrypoint also does this, but an
# explicit run is easier to scan for warnings).
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    run --rm --entrypoint sh backend -lc "python manage.py migrate --no-input"
```

### 7.4 Backups (recommended before going live)

```bash
# Postgres dump → host filesystem.
sudo docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec -T postgres pg_dump -U nirogidhara nirogidhara | gzip > \
    /opt/nirogidhara-command/backups/db-$(date +%F).sql.gz

# Static + media (rarely needed but cheap to copy).
sudo docker run --rm \
    -v nirogidhara_static_volume:/from \
    -v /opt/nirogidhara-command/backups:/to alpine \
    sh -c 'cd /from && tar czf /to/static-$(date +%F).tgz .'
```

Schedule via cron once the customer DB is live.

---

## 8. Resource safety on a shared VPS

Postzyo + OpenClaw already run on this host. Do **not** prune Docker
state globally without checking with the user.

```bash
# Safe — read-only.
docker stats
sudo docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker system df
docker network ls
docker volume ls | grep nirogidhara

# DANGER — deletes images, networks, volumes for ALL stacks.
# docker system prune -a --volumes      ← only on explicit user approval.
```

Tuning knobs that are safe to dial up after watching `docker stats` for
a day:

- `worker.command` → bump `--concurrency=1` to 2 once memory is stable.
- `nirogidhara-redis` → keep `--appendonly yes`; rotate `appendonly.aof`
  via Redis if it grows past a few hundred MB.
- Postgres → 16-alpine ships sensible defaults; only tune
  `max_connections` if observed contention happens.

---

## 8.5 Troubleshooting — duplicate Postgres index on first migrate

If the **first** `migrate` against a fresh Postgres errors out with one
or more of:

```
django.db.utils.ProgrammingError: relation "calls_calltranscriptline_call_id_5bc33dc3" already exists
django.db.utils.ProgrammingError: relation "calls_calltranscriptline_call_id_5bc33dc3_like" already exists
```

…you have hit a known production-only data race in
`apps/calls/migrations/0002_phase2d_vapi_fields.py`. Django creates the
support indexes for the FK in two passes; under Postgres 16 + Daphne
+ Celery worker / beat all booting at once, a stale index from a prior
half-applied migration can survive into the next attempt.

**Fix without dropping the database:**

```bash
cd /opt/nirogidhara-command

# 1) Stop everything that talks to the schema. Keep only Postgres + Redis up.
docker compose -f docker-compose.prod.yml --env-file .env.production stop \
    backend worker beat nginx
docker compose -f docker-compose.prod.yml --env-file .env.production up -d \
    postgres redis

# 2) Drop the two clashing indexes (idempotent — safe to re-run).
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c \
    'DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3; DROP INDEX IF EXISTS calls_calltranscriptline_call_id_5bc33dc3_like;'

# 3) Re-run migrate via a one-shot backend container (entrypoint runs
#    migrate automatically, so we override it to a plain shell here to
#    avoid double-collectstatic in the recovery path).
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm \
    --entrypoint sh backend -lc "python manage.py migrate --no-input"

# 4) Bring the rest of the stack back up. `--pull never` keeps the local
#    image in place (the recovery already proved it works).
docker compose -f docker-compose.prod.yml --env-file .env.production \
    up -d --build --pull never
```

If multiple FK index variants exist (e.g. after several failed retries),
sweep all of them in one shot:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
    psql -U nirogidhara -d nirogidhara -c "DO \$\$ DECLARE r RECORD; BEGIN FOR r IN SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname LIKE 'calls_calltranscriptline_call_id_%' LOOP EXECUTE format('DROP INDEX IF EXISTS %I', r.indexname); END LOOP; END \$\$;"
```

> **Do not** edit `apps/calls/migrations/0002_phase2d_vapi_fields.py` to
> "fix" this in the repo. Migration files are append-only history; a
> patch that works for one customer's DB will silently desync from
> another. Keep the workaround in this runbook.

After the sweep:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
curl -fsS http://127.0.0.1:18020/api/healthz/
```

The backend should boot cleanly and `migrate` should be a no-op.

## 9. Security checklist before customers go live

- [ ] `DJANGO_SECRET_KEY` and `JWT_SIGNING_KEY` are unique, long, and never committed.
- [ ] `DEBUG=false` everywhere in `.env.production`.
- [ ] `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` all include `ai.nirogidhara.com` and nothing wildcarded.
- [ ] Postgres password is strong and matches the value embedded in `DATABASE_URL`.
- [ ] `WHATSAPP_PROVIDER`, `RAZORPAY_MODE`, `DELHIVERY_MODE`, `VAPI_MODE`, `META_MODE` all stay `mock` until Prarit confirms each integration's live credentials.
- [ ] `AI_PROVIDER` stays `disabled` until OpenAI / Anthropic keys are in place.
- [ ] `WHATSAPP_DEV_PROVIDER_ENABLED=false` (the Baileys stub refuses to load anyway when DEBUG=false, but this is belt + braces).
- [ ] Postgres `pg_dump` backup taken before the first real customer payment / order.
- [ ] Host Nginx (or Traefik) terminates TLS; HTTP 80 either redirects to HTTPS or is closed at the firewall.
- [ ] `docker stats` confirms the new stack is leaving headroom for Postzyo + OpenClaw.
- [ ] **Phase 5C — WhatsApp AI Chat Sales Agent.** `WHATSAPP_AI_AUTO_REPLY_ENABLED=false` until: (a) `AI_PROVIDER=openai` + `OPENAI_API_KEY` set, (b) the locked greeting template (`whatsapp.greeting`) is synced and approved, (c) `Claim` rows exist for every product the agent must explain, (d) a controlled run on test numbers passes. Flip the env to `true` and restart the backend / worker / beat containers to enable auto-mode.

---

## 10. What's intentionally NOT here

This deployment scaffold ships **only** Phase 1 → 5B. The following stay
locked out at the application layer regardless of how the container is
configured:

- AI Chat Sales Agent (Phase 5C)
- WhatsApp inbound auto-reply
- Chat-to-call handoff
- Order booking from WhatsApp chat
- Discount automation / rescue-discount flow
- Campaign / broadcast WhatsApp sends
- Freeform outbound WhatsApp text
- CAIO-originated customer messages

If the deploy somehow turns those on, **stop the rollout** and re-read
`docs/WHATSAPP_INTEGRATION_PLAN.md` and `nd.md` §2 hard stops.
