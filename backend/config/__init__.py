"""Expose the Celery app at module import so Django picks it up on startup.
``app`` is also what the ``celery -A config worker -B`` CLI looks up.
"""
from __future__ import annotations

from .celery import app as celery_app

__all__ = ("celery_app",)
