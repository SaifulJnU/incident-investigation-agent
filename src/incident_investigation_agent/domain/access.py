"""Who is calling, and which services they may investigate."""

from __future__ import annotations

from dataclasses import dataclass

ADMIN_ROLE = "incident-admin"
ALL_SERVICES = "*"


@dataclass(frozen=True)
class Principal:
    subject: str
    name: str
    services: frozenset[str]
    roles: frozenset[str]

    @property
    def allows_all(self) -> bool:
        return ALL_SERVICES in self.services or ADMIN_ROLE in self.roles

    def may_access(self, service: str) -> bool:
        return self.allows_all or service in self.services

    def list_scope(self) -> frozenset[str] | None:
        """None means every service. An empty set means none."""
        if self.allows_all:
            return None
        return self.services
