"""Phase 9F — CEO AI Orchestration V1.

Business-level synthesis layer over the Phase 9A–9E agent snapshots.
Produces ONE deterministic daily director briefing combining
Customer Success, RTO Prevention, CFO, Data Analyst, and Calling
Team Leader output. The agent NEVER triggers WhatsApp, calls,
payments, or shipments. Downstream gates (Phase 5D / 5E / 7E-Live-B
/ 7G-Live) remain the only paths to real customer action.

Phase 9F does NOT touch the legacy ``ai_governance.CeoBriefing``
model or the existing ``ai-daily-briefing-morning`` /
``ai-daily-briefing-evening`` beat schedule entries. It adds a new
table and a new beat entry alongside.
"""
