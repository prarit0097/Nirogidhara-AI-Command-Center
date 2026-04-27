"""Per-agent runtime services — Phase 3B.

Each module exposes:

- ``build_input_payload()`` — pulls a safe, read-only DB slice and shapes
  it into the JSON payload that ``run_readonly_agent_analysis`` will
  forward to the LLM (or stub-out as ``skipped`` when AI is disabled).
- ``run(triggered_by="")`` — high-level entry point: builds the payload,
  dispatches the agent run, and returns the persisted ``AgentRun``.

These services NEVER write to business-state models (leads, orders,
payments, shipments, calls). The only side effects are the ``AgentRun``
row, optional AuditEvent rows, and the ``CeoBriefing`` table when the
CEO agent succeeds (the briefing table is treated as a derived view).

CAIO is hard-stopped to read/audit only — see ``caio.py`` for details.
"""
from __future__ import annotations

from . import ads, caio, ceo, cfo, compliance, rto, sales_growth

AGENTS = {
    "ceo": ceo,
    "caio": caio,
    "ads": ads,
    "rto": rto,
    "sales_growth": sales_growth,
    "cfo": cfo,
    "compliance": compliance,
}

__all__ = ("AGENTS", "ads", "caio", "ceo", "cfo", "compliance", "rto", "sales_growth")
