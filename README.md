# Nirogidhara AI Command Center

AI Business Operating System for Ayurveda sales, CRM, AI calling, payments, Delhivery delivery tracking, RTO control, AI agents, CEO AI, CAIO governance, reward/penalty engine and learning loop.

## Project Structure

nirogidhara-command/
  frontend/   # Lovable React/Vite frontend
  backend/    # Future Django + DRF backend placeholder
  docs/       # Planning and architecture docs

## Frontend

cd frontend
npm install
npm run dev
npm run build

## Backend

Backend is planned but not created yet.

Future backend:
- Django
- Django REST Framework
- PostgreSQL
- Celery
- Redis
- Django Channels

## Important Architecture Rule

Frontend should consume APIs only.
Business logic must stay in backend services.
