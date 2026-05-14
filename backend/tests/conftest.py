from __future__ import annotations

import pytest
from django.test.utils import override_settings


@pytest.fixture(autouse=True, scope="session")
def _force_eager_celery():
    """Pin Celery to eager mode AND every integration adapter to
    ``mock`` for the whole test session.

    **Celery (original purpose).** Production VPS ``.env.production``
    sets ``CELERY_TASK_ALWAYS_EAGER=false`` so the real Celery worker
    + Redis broker pick up tasks. When VPS pytest is run in the same
    container, that env value flows into Django settings and
    ``.delay()`` no longer runs synchronously — which silently
    breaks any test that asserts on audit kinds the queued task is
    supposed to emit (Phase 5B sent / Phase 5C AI-trigger / Phase 4B
    sweep, etc.).

    Forcing eager mode here keeps ``.delay()`` synchronous in tests
    without changing production runtime. Eager-propagates is enabled
    so any task exception surfaces directly in the test assertion
    instead of being swallowed by Celery.

    **Test Hygiene Hotfix-1 (Phase 8F-Hotfix-2 follow-up).** The
    VPS ``.env.production`` ships with non-mock values for several
    integration adapters:

    - ``RAZORPAY_MODE=test`` (real Razorpay TEST API)
    - ``WHATSAPP_PROVIDER=meta_cloud`` (real Meta Cloud client)
    - ``WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true`` (final-send
      allow-list guard active)

    When pytest is run on the VPS without overriding these, tests
    that don't carry their own ``override_settings`` (the bulk of
    the suite) inherit them. The consequences observed on the VPS
    full-suite run were:

    - Phase 4D / writes — real Razorpay TEST API created live
      ``rzp.io`` payment links; Razorpay 500s + URL mismatches
      cascaded into ~10 failures.
    - Phase 5A webhook — Meta Cloud signature verification rejected
      the test fixtures' app-secret HMAC because the live
      ``META_WA_APP_SECRET`` overrode the test override.
    - Phase 5A / 5B / 5C / 5D / 5E sends — the final-send
      limited-mode allow-list guard refused outbounds to any phone
      not in ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`` (which is
      empty on the VPS at suite time), surfacing as
      ``Limited test mode: destination not on allow-list`` across
      ~30 tests.

    None of these were product defects. They were test-isolation
    leaks from real ``.env.production`` values flowing through.
    The session-wide ``override_settings`` below pins every
    integration adapter back to ``mock`` (and turns the limited-
    test-mode guard OFF) for the test session only. Tests that
    intentionally need a non-mock value already use their own
    ``override_settings`` context, which wins over the session pin
    inside that test — we do not touch those.
    """
    with override_settings(
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_TASK_EAGER_PROPAGATES=True,
        # Razorpay payment-link adapter: mock returns a stable
        # `plink_test_*` placeholder URL; test mode would hit the
        # real Razorpay TEST API.
        RAZORPAY_MODE="mock",
        # WhatsApp provider: mock writes outbound rows without
        # touching Meta Cloud; meta_cloud + limited-test-mode guard
        # refuses every send to phones not in the allow-list.
        WHATSAPP_PROVIDER="mock",
        WHATSAPP_LIVE_META_LIMITED_TEST_MODE=False,
        # The remaining provider adapters — pinning them to mock
        # here keeps the pin posture homogeneous and prevents the
        # next `.env.production` flip from silently leaking into
        # tests.
        DELHIVERY_MODE="mock",
        VAPI_MODE="mock",
        META_MODE="mock",
    ):
        yield


@pytest.fixture(autouse=True)
def _enable_db(db):
    """Every endpoint test hits the DB — use the standard pytest-django fixture."""
    yield


@pytest.fixture
def seeded(db):
    """Run the seed_demo_data command once for the test session.

    Each test gets a transaction-scoped DB but the seed command lives in the
    same transaction, so we can read data without persisting between tests.
    """
    from django.core.management import call_command

    call_command("seed_demo_data", "--reset")


# ---------- Phase 2A — auth fixtures for write-endpoint tests ----------


@pytest.fixture
def operations_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="ops",
        password="ops12345",
        email="ops@nirogidhara.test",
    )
    user.role = User.Role.OPERATIONS
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def viewer_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="viewer",
        password="viewer12345",
        email="viewer@nirogidhara.test",
    )
    user.role = User.Role.VIEWER
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def admin_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="admin_user",
        password="admin12345",
        email="admin@nirogidhara.test",
    )
    user.role = User.Role.ADMIN
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def auth_client():
    """Factory that returns an APIClient pre-authenticated as the given user.

    Usage:
        client = auth_client(operations_user)
    """
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    def _make(user) -> APIClient:
        client = APIClient()
        if user is not None:
            access = str(RefreshToken.for_user(user).access_token)
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client

    return _make
