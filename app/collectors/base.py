from abc import ABC, abstractmethod

from app.models import RawItem


class Collector(ABC):
    """One source, one schedule, isolated so its failure can't cascade.

    fetch() is a single polling cycle: given the persisted cursor, return the
    new items and the advanced cursor. It must not raise for empty results —
    only for genuine failures, which the scheduler counts toward the circuit
    breaker. All returned text is untrusted and only ever pattern-matched.
    """

    #: stable id, e.g. "rss:coindesk"
    name: str
    #: coarse type used in the schema, e.g. "rss"
    source_type: str

    @abstractmethod
    async def fetch(self, cursor: dict) -> tuple[list[RawItem], dict]: ...
