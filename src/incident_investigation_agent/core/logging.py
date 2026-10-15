"""Process logging. The API and the worker each call configure_logging once at startup."""

from __future__ import annotations

import contextvars
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_case_id: contextvars.ContextVar[str] = contextvars.ContextVar("case_id", default="")
_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")
_install_lock = threading.Lock()
_installed = False


def install_record_factory() -> None:
    """Stamp every log record with the case and run of the current thread."""
    global _installed
    with _install_lock:
        if _installed:
            return
        previous = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = previous(*args, **kwargs)
            record.case_id = _case_id.get()
            record.run_id = _run_id.get()
            return record

        logging.setLogRecordFactory(factory)
        _installed = True


class _CaseFileHandler(logging.StreamHandler):
    _case_file = True


class InvestigationFormatter(logging.Formatter):
    """Append case and run when this line was written during an investigation."""

    def format(self, record: logging.LogRecord) -> str:
        case_id = getattr(record, "case_id", "") or ""
        run_id = getattr(record, "run_id", "") or ""
        if (case_id or run_id) and not getattr(record, "_case_file_noted", False):
            record.msg = f"{record.getMessage()} case={case_id or '-'} run={run_id or '-'}"
            record.args = ()
            record._case_file_noted = True
        return super().format(record)


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    install_record_factory()
    formatter = InvestigationFormatter("%(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    if any(getattr(handler, "_case_file", False) for handler in root.handlers):
        root.setLevel(level)
        return
    if not root.handlers:
        root.setLevel(level)
        handler = _CaseFileHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
        return
    package = logging.getLogger("incident_investigation_agent")
    package.setLevel(level)
    if any(getattr(handler, "_case_file", False) for handler in package.handlers):
        return
    handler = _CaseFileHandler()
    handler.setFormatter(formatter)
    package.addHandler(handler)
    package.propagate = False


@contextmanager
def bind_investigation(case_id: object | None, run_id: object | None) -> Iterator[None]:
    """Make log lines on this thread name the case and the run."""
    install_record_factory()
    case_token = _case_id.set("" if case_id is None else str(case_id))
    run_token = _run_id.set("" if run_id is None else str(run_id))
    try:
        yield
    finally:
        _case_id.reset(case_token)
        _run_id.reset(run_token)


def in_context(function):
    """Return a callable that keeps this thread's case and run.

    Copy the context here, on the calling thread. A worker thread starts empty,
    so copying inside that thread would drop the case and the run. Each call
    gets its own copy. One context must not be shared across threads.
    """
    context = contextvars.copy_context()

    def _run(*args, **kwargs):
        return context.run(function, *args, **kwargs)

    return _run
