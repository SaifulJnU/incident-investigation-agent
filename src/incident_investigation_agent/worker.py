"""Process entry. Claims queued investigations and does not serve HTTP."""

from __future__ import annotations

import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.core.logging import configure_logging
from incident_investigation_agent.db.session import session_factory_from_url
from incident_investigation_agent.services.heartbeat import (
    BEAT_INTERVAL_SECONDS,
    clear_beat,
    record_beat,
)
from incident_investigation_agent.services.investigation import (
    claim_batch,
    execute,
    release_held_runs,
    release_stale_runs,
    wait_for_database,
)

BATCH = 4

log = logging.getLogger("incident_investigation_agent.worker")

_held: set = set()
_held_guard = threading.Lock()
_beat_lock = threading.Lock()


def hold_run(run_id) -> None:
    with _held_guard:
        _held.add(run_id)


def drop_run(run_id) -> None:
    with _held_guard:
        _held.discard(run_id)


def held_run_ids() -> list:
    with _held_guard:
        return list(_held)


def release_on_stop(factory, run_ids) -> int:
    """Release the runs this process was working on when a deploy stopped it."""
    ids = list(run_ids)
    if not ids:
        return 0
    with factory() as session:
        released = release_held_runs(session, ids)
        session.commit()
        return released


def silence_beat(factory) -> None:
    """Remove the heartbeat so a stopped worker does not look alive."""
    with _beat_lock:
        with factory() as session:
            clear_beat(session)
            session.commit()


def run_heartbeat(factory, stop: threading.Event, interval: float = BEAT_INTERVAL_SECONDS) -> None:
    """Write a beat until stop is set, including while a note is in progress."""
    while not stop.is_set():
        try:
            with _beat_lock:
                if stop.is_set():
                    return
                with factory() as session:
                    record_beat(session)
                    session.commit()
        except Exception:
            log.exception("worker heartbeat failed")
        stop.wait(interval)


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    if not settings.database_url.startswith("postgresql"):
        raise SystemExit("The worker requires PostgreSQL.")
    factory = session_factory_from_url(settings.database_url)
    wait_for_database(factory)
    stop = threading.Event()
    _listen_for_stop(factory, stop)
    threading.Thread(
        target=run_heartbeat,
        args=(factory, stop),
        name="worker-heartbeat",
        daemon=True,
    ).start()
    names = ",".join(enabled_connectors(settings.app_env, settings.connectors))
    log.info(
        "worker ready provider=%s env=%s connectors=%s",
        settings.model_provider,
        settings.app_env,
        names,
    )
    while True:
        try:
            worked = _run_available(factory, settings)
        except Exception:
            log.exception("worker loop failed")
            worked = False
        if not worked:
            time.sleep(1)


def _run_available(factory, settings: Settings) -> bool:
    """Claim up to BATCH queued cases. Each case keeps its own note."""
    with factory() as session:
        release_stale_runs(session, older_than_minutes=settings.run_timeout_minutes)
        runs = claim_batch(session, BATCH)
        if not runs:
            session.commit()
            return False
        run_ids = [run.id for run in runs]
        for run_id in run_ids:
            hold_run(run_id)
        try:
            session.commit()
        except Exception:
            for run_id in run_ids:
                drop_run(run_id)
            raise
    try:
        if len(run_ids) == 1:
            execute(factory, settings, run_ids[0])
            return True
        with ThreadPoolExecutor(max_workers=len(run_ids)) as pool:
            list(pool.map(lambda run_id: execute(factory, settings, run_id), run_ids))
        return True
    finally:
        for run_id in run_ids:
            drop_run(run_id)


def _listen_for_stop(factory, stop: threading.Event) -> None:
    def _on_stop(signum, _frame):
        stop.set()
        try:
            silence_beat(factory)
        except Exception:
            log.exception("could not clear the worker heartbeat")
        try:
            released = release_on_stop(factory, held_run_ids())
            log.info("worker stopped signal=%s released=%s", signum, released)
        except Exception:
            log.exception("could not release held runs")
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)


if __name__ == "__main__":
    main()
