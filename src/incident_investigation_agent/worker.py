"""Process entry. Claims queued investigations and does not serve HTTP."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.core.logging import configure_logging
from incident_investigation_agent.db.session import session_factory_from_url
from incident_investigation_agent.services.investigation import claim_batch, execute, wait_for_database

BATCH = 4

log = logging.getLogger("incident_investigation_agent.worker")


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    if not settings.database_url.startswith("postgresql"):
        raise SystemExit("The worker requires PostgreSQL.")
    factory = session_factory_from_url(settings.database_url)
    wait_for_database(factory)
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
        runs = claim_batch(session, BATCH)
        if not runs:
            session.rollback()
            return False
        run_ids = [run.id for run in runs]
        session.commit()
    if len(run_ids) == 1:
        execute(factory, settings, run_ids[0])
        return True
    with ThreadPoolExecutor(max_workers=len(run_ids)) as pool:
        list(pool.map(lambda run_id: execute(factory, settings, run_id), run_ids))
    return True


if __name__ == "__main__":
    main()
