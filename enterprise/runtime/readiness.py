"""Pure portable runtime readiness aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PortableReadiness:
    process_alive: bool
    role_health: bool
    instance_health: bool
    startup_ready: bool
    release_match: bool
    runtime_trust_ready: bool

    @property
    def ready(self) -> bool:
        return all(asdict(self).values())

    def snapshot(self) -> dict[str, bool]:
        return {**asdict(self), "ready": self.ready}


def classify_portable_readiness(
    *,
    process_alive: bool,
    role_health: bool,
    instance_health: bool,
    startup_ready: bool,
    release_match: bool,
    runtime_trust_ready: bool,
) -> PortableReadiness:
    values = (process_alive, role_health, instance_health, startup_ready, release_match, runtime_trust_ready)
    if any(type(value) is not bool for value in values):
        raise ValueError("portable readiness inputs are invalid")
    return PortableReadiness(*values)
