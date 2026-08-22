import hashlib
from dataclasses import dataclass, field
from datetime import datetime

SEP = "|"


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    h.update(SEP.join(p or "" for p in parts).encode("utf-8"))
    return h.hexdigest()


@dataclass
class Event:
    """One normalised item, ready for triage and storage."""

    source: str
    source_type: str
    title: str
    url: str = ""
    author: str | None = None
    raw_text: str = ""
    published_at: datetime | None = None
    entities: list[dict] = field(default_factory=list)
    source_reputation: float = 0.5

    # Filled by triage before insert.
    triage_score: float = 0.0
    triage_kept: bool = False
    triage_reasons: list[str] = field(default_factory=list)

    @property
    def raw_hash(self) -> str:
        # Exact-dedup key: same source_type + url (or title) is the same item,
        # even if re-fetched. Falls back to title when there is no url.
        return _sha(self.source_type, self.url or self.title, self.title)

    @property
    def title_hash(self) -> str:
        return _sha(self.title.strip().lower())


@dataclass
class RawItem:
    """Archive payload paired with its normalised event."""

    payload: dict
    event: Event
