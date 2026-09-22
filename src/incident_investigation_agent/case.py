"""A small on-disk case file the investigation tools read and write."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Evidence:
    kind: str
    summary: str
    source: str
    recorded_at: str


class CaseStore:
    def __init__(self, directory: Path) -> None:
        self.path = directory / "case.json"

    def add(self, kind: str, summary: str, source: str) -> Evidence:
        item = Evidence(
            kind=kind.strip().lower(),
            summary=summary.strip(),
            source=source.strip() or "operator",
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        items = self._read()
        items.append(item)
        self._write(items)
        return item

    def list(self) -> list[Evidence]:
        return self._read()

    def _read(self) -> list[Evidence]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Evidence(**entry) for entry in raw]

    def _write(self, items: list[Evidence]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(item) for item in items]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
