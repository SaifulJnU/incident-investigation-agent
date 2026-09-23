"""Process entry. Claims queued investigations and does not serve HTTP."""

from __future__ import annotations

import logging
import time

from incident_investigation_agent.core.config import Settings, enabled_connectors
from incident_investigation_agent.core.logging import configure_logging
from incident_investigation_agent.db.session import session_factory_from_url
from incident_investigation_agent.services.investigation import run_once, wait_for_database

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
            worked = run_once(factory, settings)
        except Exception:
            log.exception("worker loop failed")
            worked = False
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
