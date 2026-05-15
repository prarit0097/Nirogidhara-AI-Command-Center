"""Phase 10A — Diagnostics module.

Read-only diagnostic queries that surface operational state for the
Director. Diagnostics NEVER mutate business data, never call
external providers (WhatsApp / Razorpay / Delhivery / Vapi), and
never trigger outbound action. Any real action (e.g. sending a
payment reminder for a pending payment) continues to require the
existing approval-gated CLI workflows (Phase 7E-Live-B, etc).
"""

default_app_config = "apps.diagnostics.apps.DiagnosticsConfig"
