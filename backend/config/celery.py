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
    # Phase 9E - Calling Team Leader Agent V1. Recommendations-only daily
    # call-performance snapshot; 12:00 IST default (after Data Analyst).
    # Never triggers outbound action.
    ctl_hour = getattr(settings, "AI_CALLING_TEAM_LEADER_DAILY_HOUR", 12)
    ctl_minute = getattr(settings, "AI_CALLING_TEAM_LEADER_DAILY_MINUTE", 0)
    # Phase 9F - CEO AI Orchestration V1. Recommendations-only daily
    # synthesis briefing rolling up Phase 9A-9E snapshots; 13:00 IST
    # default (after all five upstream agents). Never triggers outbound
    # action. Independent of the legacy ai-daily-briefing-* tasks.
    ceo_orch_hour = getattr(settings, "AI_CEO_ORCHESTRATION_DAILY_HOUR", 13)
    ceo_orch_minute = getattr(
        settings, "AI_CEO_ORCHESTRATION_DAILY_MINUTE", 0
    )
    # Phase 11A - Transcript Ingestion Pipeline V1. Pulls Vapi
    # transcripts for backlogged Call rows. 23:00 IST default — end of
    # day so all completed calls have time to flush their webhooks
    # before the active pull runs. Never sends WhatsApp / makes a
    # call / dispatches a shipment.
    transcript_ingest_hour = getattr(
        settings, "TRANSCRIPT_INGESTION_DAILY_HOUR", 23
    )
    transcript_ingest_minute = getattr(
        settings, "TRANSCRIPT_INGESTION_DAILY_MINUTE", 0
    )
    transcript_ingest_limit = getattr(
        settings, "TRANSCRIPT_INGESTION_DAILY_LIMIT", 100
    )
    # Phase 11B - Call Quality Scorer V1. Runs 30 minutes after the
    # Phase 11A transcript ingest so newly-ingested transcripts get
    # scored the same evening. Recommendations-only; never sends
    # WhatsApp / makes a call / mutates business state.
    call_quality_hour = getattr(
        settings, "CALL_QUALITY_SCORING_DAILY_HOUR", 23
    )
    call_quality_minute = getattr(
        settings, "CALL_QUALITY_SCORING_DAILY_MINUTE", 30
    )
    call_quality_limit = getattr(
        settings, "CALL_QUALITY_SCORING_DAILY_LIMIT", 100
    )

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
        "calling-team-leader-daily": {
            "task": "apps.agents.calling_team_leader.tasks."
            "run_calling_team_leader_agent_daily",
            "schedule": crontab(hour=ctl_hour, minute=ctl_minute),
        },
        "ceo-orchestration-daily": {
            "task": "apps.agents.ceo_orchestration.tasks."
            "run_ceo_orchestration_agent_daily",
            "schedule": crontab(
                hour=ceo_orch_hour, minute=ceo_orch_minute
            ),
        },
        "transcript-ingestion-daily": {
            "task": "apps.calls.tasks.ingest_transcript_backlog_daily",
            "schedule": crontab(
                hour=transcript_ingest_hour,
                minute=transcript_ingest_minute,
            ),
            "args": (transcript_ingest_limit,),
        },
        "call-quality-scoring-daily": {
            "task": "apps.calls.tasks.score_call_transcripts_daily",
            "schedule": crontab(
                hour=call_quality_hour,
                minute=call_quality_minute,
            ),
            "args": (call_quality_limit,),
        },
    }


# Beat schedule is materialised lazily by Celery beat; we expose
# ``build_beat_schedule()`` for the scheduler-status endpoint and tests.
app.conf.beat_schedule = build_beat_schedule()


__all__ = ("app", "build_beat_schedule")
