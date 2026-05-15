"""Phase 9B — RTO Prevention Agent V1.

Recommendations-only deterministic scoring of in-flight orders'
return-to-origin risk. The agent NEVER directly triggers calls,
WhatsApp sends, discount creation, shipment mutation, or payment
mutation. Every recommendation is a structured snapshot that
downstream operator-approved gates (Phase 5D lifecycle, Phase 5E
rescue discount, Phase 7E-Live-B real customer WhatsApp, Phase
7G-Live real customer dispatch) may later act on.
"""
