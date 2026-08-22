"""Stage-1 naive triage. Cheap, explainable, tuned for recall — Phase 2 adds
the embedding + frontier-model Stage 2. Every score carries its reasons, and
killed events are retained in the DB, because a filter you can't audit is a
filter you can't tune.

Weighted factors (0-1 each):
  materiality       keyword/entity hits against the watchlist
  source_reputation configured per-source trust
  novelty           not seen a near-identical title recently (naive: exact
                    title hash; embeddings replace this in Phase 2)
  specificity       has a url, has entities, has substance
"""
from app.models import Event

WEIGHTS = {
    "materiality": 0.35,
    "source_reputation": 0.25,
    "novelty": 0.20,
    "specificity": 0.20,
}


def score(event: Event, is_novel: bool, high_signal: set[str]) -> tuple[float, list[str]]:
    reasons: list[str] = []

    n_hits = len(event.entities)
    n_high = sum(
        1 for e in event.entities if e.get("value", "").lower() in high_signal
    )
    # High-signal terms count double, capped so one item can't dominate.
    materiality = min((n_hits + n_high) / 4.0, 1.0)
    if n_hits:
        kinds = sorted({e["type"] for e in event.entities})
        reasons.append(f"materiality: {n_hits} hits ({', '.join(kinds)})")

    reputation = max(0.0, min(event.source_reputation, 1.0))

    novelty = 1.0 if is_novel else 0.2
    if not is_novel:
        reasons.append("novelty: similar title seen recently")

    spec = 0.0
    if event.url:
        spec += 0.4
    if event.entities:
        spec += 0.3
    if len(event.raw_text) > 200:
        spec += 0.3
    specificity = min(spec, 1.0)

    total = (
        WEIGHTS["materiality"] * materiality
        + WEIGHTS["source_reputation"] * reputation
        + WEIGHTS["novelty"] * novelty
        + WEIGHTS["specificity"] * specificity
    )
    reasons.append(
        f"score {total:.2f} = "
        f"mat {materiality:.2f}/rep {reputation:.2f}/"
        f"nov {novelty:.2f}/spec {specificity:.2f}"
    )
    return round(total, 4), reasons
