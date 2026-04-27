"""Tiny prefix-keyed ID generator used by Phase 2A write services.

All Phase 1 models use string PKs of the form ``PREFIX-NUMBER`` so seeded rows
match the frontend mockData fixtures. Write endpoints need to mint the next
ID server-side; this helper centralises that math (and stays trivially testable
without a network call).

The generator is intentionally read-then-write inside a ``transaction.atomic()``
block at the call site — sufficient for dev volumes. When we move to Postgres
+ concurrent writers in Phase 2B we'll switch to a sequence / advisory lock.

Note: we don't rely on ``created_at`` because some Phase 1 models (e.g.
``crm.Customer``) don't define it. Walking PKs is fine for dev row counts.
"""
from __future__ import annotations

from django.db.models import Model


def next_id(prefix: str, model: type[Model], base: int) -> str:
    """Return the next ``PREFIX-N`` ID for the given model.

    Walks every existing PK, picks the max numeric suffix, increments it. Falls
    back to ``base`` when the table is empty or no IDs match the pattern.
    """
    matching: list[int] = []
    for pk in model.objects.values_list("pk", flat=True):
        try:
            matching.append(int(str(pk).rsplit("-", 1)[-1]))
        except (ValueError, IndexError):
            continue
    if not matching:
        return f"{prefix}-{base}"
    return f"{prefix}-{max(matching) + 1}"
