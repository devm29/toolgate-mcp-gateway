from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PeerTool:
    upstream: str
    name: str
    exposed_name: str


@dataclass(frozen=True, slots=True)
class ScanContext:
    """What the scanner knows about the rest of the fleet; shadowing is only detectable relative to peers."""

    upstream: str
    peers: tuple[PeerTool, ...] = ()
    trusted_domains: frozenset[str] = field(default_factory=frozenset)

    def foreign_peers(self) -> tuple[PeerTool, ...]:
        return tuple(p for p in self.peers if p.upstream != self.upstream)
