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
    # Phase 9A - Customer Success / Reorder Agent V1. Recommendations-only;
    # 08:00 IST default (env-shiftable). Never triggers outbound action.
    cs_hour = getattr(settings, "AI_CUSTOMER_SUCCESS_DAILY_HOUR", 8)
    cs_minute = getattr(settings, "AI_CUSTOMER_SUCCESS_DAILY_MINUTE", 0)
    # Phase 9B - RTO Prevention Agent V1. Recommendations-only; 09:00 IST
    # default (after the Customer Success sweep). Never triggers outbound
    # action.
    rto_hour = getattr(settings, "AI_RTO_PREVENTION_DAILY_HOUR", 9)
    rto_minute = getattr(settings, "AI_RTO_PREVENTION_DAILY_MINUTE", 0)
    # Phase 9C - CFO Agent V1. Recommendations-only business-level daily
    # financial snapshot; 10:00 IST default (after the customer + order
    # agents). Never triggers outbound action.
    cfo_hour = getattr(settings, "AI_CFO_DAILY_HOUR", 10)
    cfo_minute = getattr(settings, "AI_CFO_DAILY_MINUTE", 0)
    # Phase 9D - Data Analyst Agent V1. Recommendations-only operational
    # daily funnel snapshot; 11:00 IST default (after CFO). Never
    # triggers outbound action.
    da_hour = getattr(settings, "AI_DATA_ANALYST_DAILY_HOUR", 11)
    da_minute = getattr(settings, "AI_DATA_ANALYST_DAILY_MINUTE", 0)

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
        "customer-success-daily": {
            "task": "apps.agents.customer_success.tasks."
            "run_customer_success_agent_daily",
            "schedule": crontab(hour=cs_hour, minute=cs_minute),
        },
        "rto-prevention-daily": {
            "task": "apps.agents.rto_prevention.tasks."
            "run_rto_prevention_agent_daily",
            "schedule": crontab(hour=rto_hour, minute=rto_minute),
        },
        "cfo-daily": {
            "task": "apps.agents.cfo.tasks.run_cfo_agent_daily",
            "schedule": crontab(hour=cfo_hour, minute=cfo_minute),
        },
        "data-analyst-daily": {
            "task": "apps.agents.data_analyst.tasks."
            "run_data_analyst_agent_daily",
            "schedule": crontab(hour=da_hour, minute=da_minute),
        },
    }


# Beat schedule is materialised lazily by Celery beat; we expose
# ``build_beat_schedule()`` for the scheduler-status endpoint and tests.
app.conf.beat_schedule = build_beat_schedule()


__all__ = ("app", "build_beat_schedule")
