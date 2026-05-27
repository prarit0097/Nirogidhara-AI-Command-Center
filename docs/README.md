# Documentation Index

Documentation for the Nirogidhara AI Command Center.

> **Current operational baseline: Phase 15M — Foundation Release Freeze.** Safety shell is frozen at code commit `eefd8b3`; sign-off pack created at `8fc77d6` and corrected through the docs hygiene chain `c75697f` → `c85a32e` → `966c246` → `aa0852a` → latest (see `nd.md` head-of-file for the live commit pointer). The canonical operational source of truth is [`../nd.md`](../nd.md) + [`PHASE_15M_DIRECTOR_SIGNOFF_PACK.md`](PHASE_15M_DIRECTOR_SIGNOFF_PACK.md). Next planned work is **Phase 16A — Business MVP Gap Audit** (planning-only, awaiting Director directive). The roadmap docs below cover phases up to the Phase-12D-era baseline plus the Phase 14D → 15M chrome; see `nd.md` head-of-file for current truth.

| File | Purpose |
| --- | --- |
| [`PHASE_15M_DIRECTOR_SIGNOFF_PACK.md`](PHASE_15M_DIRECTOR_SIGNOFF_PACK.md) | **Current release-freeze / Director sign-off pack** (Phase 15M). Verified baseline, freeze rule, route-wise smoke checklist, sign-off checklist, accepted risks, production safety posture, Phase 16A handoff, rollback plan. |
| [`MASTER_BLUEPRINT_V2.md`](MASTER_BLUEPRINT_V2.md) | **Historical strategic blueprint** (Master Blueprint v2.0). Reflects strategic framing as of its original revision; contains Phase 12D-era wording. Strategic / historical reference only unless updated later. Supersedes the v1.0 PDF (also historical). |
| [`RUNBOOK.md`](RUNBOOK.md) | **Operational runbook**, updated through Phase 15M. Local dev steps, Director playbooks, state semantics, Foundation Release Freeze policy. |
| [`DEPLOYMENT_VPS.md`](DEPLOYMENT_VPS.md) | Production deployment runbook for `ai.nirogidhara.com` (`/opt/nirogidhara-command`). |
| [`BACKEND_API.md`](BACKEND_API.md) | API endpoint reference (catalogues endpoints through the Phase 12D-era surfaces + Phase 15B/15C read-only additions). |
| [`FRONTEND_AUDIT.md`](FRONTEND_AUDIT.md) | Historical frontend audit snapshot (Phase 12D-era). Current UI baseline is Phase 15M. |
| [`FUTURE_BACKEND_PLAN.md`](FUTURE_BACKEND_PLAN.md) | Phased roadmap (historical Phase 12D-era SaaS runtime gate status preserved; current baseline is Phase 15M). |
| [`WHATSAPP_INTEGRATION_PLAN.md`](WHATSAPP_INTEGRATION_PLAN.md) | WhatsApp + AI Chat Sales Agent design plan (Phase 5A-0 → 5C + Phase 7E-Live-B + Phase 12C and beyond). WhatsApp live / broadcast / campaign / lifecycle / handoff / rescue / Day-20 flows all remain locked OFF unless the Director explicitly approves. |

The repo-level [`nd.md`](../nd.md) is the **canonical operational source of truth**. If `nd.md` and any document here disagree on a detail, `nd.md` wins and the document must be updated to match.

The repo-level [`CLAUDE.md`](../CLAUDE.md) / [`AGENTS.md`](../AGENTS.md) are AI-agent guardrails — read on every session.
