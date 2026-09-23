"""Evidence a case keeps. Storage and the model are outside this module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

EVIDENCE_KINDS = frozenset({"symptom", "log", "timeline", "change", "hypothesis"})


@dataclass(frozen=True)
class Evidence:
    kind: str
    summary: str
    source: str
    recorded_at: str


class EvidenceStore(Protocol):
    def add(self, kind: str, summary: str, source: str) -> Evidence: ...

    def list(self) -> list[Evidence]: ...
