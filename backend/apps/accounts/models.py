from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user with a `role` for the blueprint's RBAC matrix.

    Kept minimal in this phase — full role/permission resolution lives in
    services and is layered in Phase 2 alongside the governance UI.
    """

    class Role(models.TextChoices):
        DIRECTOR = "director", "Director"
        ADMIN = "admin", "Admin"
        OPERATIONS = "operations", "Operations"
        COMPLIANCE = "compliance", "Compliance"
        VIEWER = "viewer", "Viewer"

    role = models.CharField(max_length=32, choices=Role.choices, default=Role.VIEWER)
    display_name = models.CharField(max_length=120, blank=True)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.username
