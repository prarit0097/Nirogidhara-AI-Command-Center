from __future__ import annotations

import pytest


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
