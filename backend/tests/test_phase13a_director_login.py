"""Phase 13A — Director login JWT endpoint tests.

NEVER tests the real production Director user. Uses a synthetic fixture
user 'phase13a-test-director@example.com' that exists only during the
test run (Django creates and tears down the test DB).

Verifies the new alias at /api/v1/auth/login/ (registered in
backend/config/urls.py). The legacy /api/auth/token/ endpoint is
unaffected and not exercised here.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


LOGIN_URL = "/api/v1/auth/login/"


@pytest.fixture
def test_director(db):
    User = get_user_model()
    user = User.objects.create_user(
        username="phase13a-test-director@example.com",
        email="phase13a-test-director@example.com",
        password="phase13a-test-password-123",
        is_staff=True,
        is_superuser=True,
    )
    return user


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_login_with_valid_credentials_returns_access_token(
    api_client, test_director
):
    response = api_client.post(
        LOGIN_URL,
        {
            "email": test_director.email,
            "username": test_director.username,
            "password": "phase13a-test-password-123",
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    assert "access" in response.data
    assert isinstance(response.data["access"], str)
    assert len(response.data["access"]) > 20


@pytest.mark.django_db
def test_login_with_wrong_password_returns_401(api_client, test_director):
    response = api_client.post(
        LOGIN_URL,
        {
            "email": test_director.email,
            "username": test_director.username,
            "password": "wrong-password",
        },
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_login_with_unknown_email_returns_401(api_client):
    response = api_client.post(
        LOGIN_URL,
        {
            "email": "nonexistent@example.com",
            "username": "nonexistent@example.com",
            "password": "whatever",
        },
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_login_response_does_not_leak_password(api_client, test_director):
    response = api_client.post(
        LOGIN_URL,
        {
            "email": test_director.email,
            "username": test_director.username,
            "password": "phase13a-test-password-123",
        },
        format="json",
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "phase13a-test-password-123" not in body
