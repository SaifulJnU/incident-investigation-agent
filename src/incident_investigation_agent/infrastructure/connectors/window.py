"""The span a connector searches.

A case that started inside the lookback keeps the span ending now. A case
that started earlier is searched from that start, for the same length, so a
late investigation still reads the hour the errors began. The lookback stays
the longest span.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from incident_investigation_agent.db.models import utcnow


def search_span(
    started_at: datetime | None,
    lookback: timedelta,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime, bool]:
    """Return the start, the end, and whether the span moved to the case start.

    The third value is false when the span is the lookback ending at now.
    A missing start, or a start in the future, stays on that span.
    """
    moment = _aware(now or utcnow())
    rolling = moment - lookback
    if started_at is None:
        return rolling, moment, False
    start = _aware(started_at)
    if start >= rolling:
        return rolling, moment, False
    return start, start + lookback, True


def during(length: str, anchored: bool, start: datetime) -> str:
    """The words that name the span in an empty result.

    ``length`` is ``60 minutes`` or ``24 hours``. An unmoved span reads
    ``the last 60 minutes``. A moved span reads ``60 minutes from <start>``.
    """
    if not anchored:
        return f"the last {length}"
    return f"{length} from {stamp(start)}"


def stamp(value: datetime) -> str:
    return _aware(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_ms(value: datetime) -> int:
    return int(_aware(value).timestamp() * 1000)


def epoch_ns(value: datetime) -> int:
    aware = _aware(value)
    return int(aware.timestamp()) * 1_000_000_000 + aware.microsecond * 1_000


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
