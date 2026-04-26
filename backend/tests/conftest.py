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
