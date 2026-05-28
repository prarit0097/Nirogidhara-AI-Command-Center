# Documentation Index

Documentation for the Nirogidhara AI Command Center.

> **Current operational baseline: Phase 16B — Customer Lifecycle UI Backbone, PRODUCTION VERIFIED at commit `00c3295` (after Hotfix-2) and CLOSED.** The Phase 15 safety shell remains frozen at code commit `eefd8b3` and unchanged through Phase 16A / 16B. The canonical operational source of truth is [`../nd.md`](../nd.md) head-of-file (with [`PHASE_15M_DIRECTOR_SIGNOFF_PACK.md`](PHASE_15M_DIRECTOR_SIGNOFF_PACK.md) for the safety-shell freeze details). Phase 16A audit → Phase 16B implementation → Hotfix-1 (`8c0c6b9`, superseded) → Hotfix-2 (`00c3295`, phone-only lead uniqueness + Orders responsive layout). **Next planned work is Phase 16C — Director Daily Briefing + Team Roles UI, awaiting a separate written Director directive.** Historical docs below remain historical; `nd.md` wins for current truth.

| File | Purpose |
| --- | --- |
| [`PHASE_15M_DIRECTOR_SIGNOFF_PACK.md`](PHASE_15M_DIRECTOR_SIGNOFF_PACK.md) | **Current release-freeze / Director sign-off pack** (Phase 15M). Verified baseline, freeze rule, route-wise smoke checklist, sign-off checklist, accepted risks, production safety posture, Phase 16A handoff, rollback plan. |
| [`MASTER_BLUEPRINT_V2.md`](MASTER_BLUEPRINT_V2.md) | **Historical strategic blueprint** (Master Blueprint v2.0). Reflects strategic framing as of its original revision; contains Phase 12D-era wording. Strategic / historical reference only unless updated later. Supersedes the v1.0 PDF (also historical). |
| [`RUNBOOK.md`](RUNBOOK.md) | **Operational runbook**, updated through Phase 16B production verification (`00c3295`). Local dev steps, Director playbooks, state semantics, Foundation Release Freeze policy, Phase 16B verification checklist. |
| [`DEPLOYMENT_VPS.md`](DEPLOYMENT_VPS.md) | Production deployment runbook for `ai.nirogidhara.com` (`/opt/nirogidhara-command`). |
| [`BACKEND_API.md`](BACKEND_API.md) | API endpoint reference (Phase 12D-era surfaces + Phase 15B/15C read-only additions + **Phase 16B semantics**: phone-only Lead duplicate `409`, `POST /api/leads/import-csv/`, `GET /api/customers/{id}/timeline/`). |
| [`FRONTEND_AUDIT.md`](FRONTEND_AUDIT.md) | Historical frontend audit snapshot (Phase 12D-era). Current UI baseline is **Phase 16B — production verified at `00c3295`**. |
| [`FUTURE_BACKEND_PLAN.md`](FUTURE_BACKEND_PLAN.md) | Historical phased roadmap (Phase 12D-era SaaS runtime gate status preserved). **Current baseline is Phase 16B — production verified at `00c3295`; next planned is Phase 16C** (separate Director directive required). |
| [`WHATSAPP_INTEGRATION_PLAN.md`](WHATSAPP_INTEGRATION_PLAN.md) | WhatsApp + AI Chat Sales Agent design plan (Phase 5A-0 → 5C + Phase 7E-Live-B + Phase 12C and beyond). WhatsApp live / broadcast / campaign / lifecycle / handoff / rescue / Day-20 flows all remain locked OFF unless the Director explicitly approves. |

The repo-level [`nd.md`](../nd.md) is the **canonical operational source of truth**. If `nd.md` and any document here disagree on a detail, `nd.md` wins and the document must be updated to match.

The repo-level [`CLAUDE.md`](../CLAUDE.md) / [`AGENTS.md`](../AGENTS.md) are AI-agent guardrails — read on every session.
