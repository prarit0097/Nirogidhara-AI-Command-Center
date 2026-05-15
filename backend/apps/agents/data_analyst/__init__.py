"""Phase 9D — Data Analyst Agent V1.

Business-level recommendations-only deterministic daily operational
analytics snapshot. Computes funnel counts (lead -> call -> confirmed
order -> delivered -> reorder), conversion rates, top geographic
states, day-of-week distribution, and anomaly alert codes. The agent
NEVER triggers WhatsApp / calls / payments / shipments / discounts.
Downstream gates (Phase 5D / 5E / 7E-Live-B / 7G-Live) remain the
only paths to a real customer action.
"""
