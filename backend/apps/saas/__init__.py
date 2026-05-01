"""Phase 6A — SaaS Foundation Safe Migration.

Multi-tenant scaffolding that does NOT yet enforce per-tenant filtering on
existing tables. The current production system stays single-tenant under
a default ``Organization`` ("Nirogidhara Private Limited") + ``Branch``
("Main Branch") seeded by ``ensure_default_organization``.

LOCKED rules for this phase:

- No existing model gets an ``organization`` FK in this migration.
- No request middleware filters existing endpoints by organization yet.
- Customer / Order / Payment / Shipment / WhatsApp data stays
  un-tenant-scoped — Phase 6C will add scoped filtering once a backfill
  command + a default-org backstop are both proven safe.
- WhatsApp env flags are not touched.
- All new SaaS endpoints are read-only.
- ``OrganizationSetting`` rows flagged ``is_sensitive=True`` never appear
  in the public API (asserted in tests).
"""

default_app_config = "apps.saas.apps.SaasConfig"
