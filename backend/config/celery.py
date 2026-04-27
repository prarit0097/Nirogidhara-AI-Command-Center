"""Celery application — Phase 3C scheduler.

Local development never has to start a worker / beat process. When
``CELERY_TASK_ALWAYS_EAGER=true`` (the default for tests + dev) calling
``.delay()`` runs the task synchronously without touching Redis. The
production / staging cron is then a single command::

    celery -A config worker -B --loglevel=info

reading ``CELERY_BROKER_URL`` (default ``redis://localhost:6379/0``).

Compliance hard stop (Master Blueprint §26 #4):
- Tasks scheduled here are *read-only*. They wrap Phase 3B agent runtimes
  that never write to leads / orders / payments / shipments / calls.
- CAIO never executes. Even via the scheduler, the existing
  ``CAIO_FORBIDDEN_INTENTS`` guard refuses any execution intent.
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("nirogidhara")

# ``CELERY_*`` namespace pulls everything from Django settings.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks across every installed app.
app.autodiscover_tasks()


def build_beat_schedule() -> dict:
    """Read the Phase 3C briefing schedule from settings.

    Two slots — morning (09:00 IST) + evening (18:00 IST) by default. Hours
    and minutes are env-driven so ops can shift them without code changes.
    """
    from django.conf import settings

    morning_hour = getattr(settings, "AI_DAILY_BRIEFING_MORNING_HOUR", 9)
    morning_minute = getattr(settings, "AI_DAILY_BRIEFING_MORNING_MINUTE", 0)
    evening_hour = getattr(settings, "AI_DAILY_BRIEFING_EVENING_HOUR", 18)
    evening_minute = getattr(settings, "AI_DAILY_BRIEFING_EVENING_MINUTE", 0)

    return {
        "ai-daily-briefing-morning": {
            "task": "apps.ai_governance.tasks.run_daily_ai_briefing_task",
            "schedule": crontab(hour=morning_hour, minute=morning_minute),
            "args": ("morning",),
        },
        "ai-daily-briefing-evening": {
            "task": "apps.ai_governance.tasks.run_daily_ai_briefing_task",
            "schedule": crontab(hour=evening_hour, minute=evening_minute),
            "args": ("evening",),
        },
    }


# Beat schedule is materialised lazily by Celery beat; we expose
# ``build_beat_schedule()`` for the scheduler-status endpoint and tests.
app.conf.beat_schedule = build_beat_schedule()


__all__ = ("app", "build_beat_schedule")
