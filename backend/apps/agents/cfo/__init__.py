"""Phase 9C — CFO Agent V1.

Business-level recommendations-only deterministic daily financial
snapshot. The agent computes rolling revenue, order counts, payment
status breakdowns, AOV, RTO impact, customer mix, and a list of
alert codes — but NEVER triggers WhatsApp / calls / payments /
shipments / discounts. Downstream gates (Phase 5D / 5E / 7E-Live-B
/ 7G-Live) remain the only paths to a real customer action.
"""
