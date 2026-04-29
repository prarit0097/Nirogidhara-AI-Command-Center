# Nirogidhara AI Command Center — frontend image (Phase 5B-Deploy).
#
# Build context is the REPO ROOT (`.`), not `./frontend/`, so the nginx
# stage can read both the Vite source AND `deploy/nginx/nirogidhara.conf`.
# `docker-compose.prod.yml` wires this via:
#
#     nginx:
#       build:
#         context: .
#         dockerfile: frontend/Dockerfile
#
# Multi-stage:
#   - builder: node 20 alpine, runs `npm ci` + `npm run build` from
#              `/app/frontend`. Bakes the same-origin VITE_API_BASE_URL=/api
#              so the production bundle never points at localhost or a
#              sibling domain.
#   - runtime: nginx alpine, serves /usr/share/nginx/html and routes
#              /api/, /admin/, /ws/ to the backend container via
#              `deploy/nginx/nirogidhara.conf`.
#
# Hard rule: no secrets are baked at build time. VITE_* values seen here
# are public configuration only (they ship to the browser).
FROM node:20-alpine AS builder

WORKDIR /app/frontend

# --- Build-time env ---
# These are inlined into the JS bundle. They MUST be safe to ship to a
# browser. Production routes everything through the same Nginx, so the
# bases stay relative ("/api" + "" → derived from window.location).
ARG VITE_API_BASE_URL=/api
ARG VITE_WS_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_WS_BASE_URL=${VITE_WS_BASE_URL}

COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build


FROM nginx:1.27-alpine AS runtime

# Drop the default config and use the project-shipped one.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx/nirogidhara.conf /etc/nginx/conf.d/default.conf

# Copy the built SPA. The Vite default output is `dist/`.
COPY --from=builder /app/frontend/dist /usr/share/nginx/html

EXPOSE 80

# Nginx writes a healthy 200 on the root document — Compose can hit /.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
