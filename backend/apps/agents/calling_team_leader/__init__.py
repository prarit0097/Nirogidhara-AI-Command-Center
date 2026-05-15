"""Phase 9E — Calling Team Leader Agent V1.

Business-level recommendations-only deterministic daily call
performance snapshot. Computes call counts (24h/7d/30d), connection
rate, average duration, outcome breakdown by ``Call.status``,
per-agent metrics grouped by ``Call.agent`` (CharField), transcript
backlog, and anomaly alert codes. The agent NEVER triggers calls,
WhatsApp, payments, or shipments. Downstream gates (Phase 5D / 5E /
7E-Live-B / 7G-Live) remain the only paths to real customer action.
"""
