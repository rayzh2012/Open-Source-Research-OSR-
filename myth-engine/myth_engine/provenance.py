from __future__ import annotations

import re
import unicodedata
from typing import Any


PROVENANCE_FIELDS = (
    "em ic_locality".replace(" ", ""),
    "informant_location",
    "collection_location",
    "performance_location",
    "publication_section_label",
    "analyst_geography",
    "collector",
    "narrator",
)


def _canon(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


def canonical_alias(value: Any, alias_map: dict[str, str] | None = None) -> str:
    key = _canon(value)
    if not alias_map:
        return key
    normalized_aliases = {_canon(k): _canon(v) for k, v in alias_map.items()}
    seen: set[str] = set()
    while key in normalized_aliases and key not in seen:
        seen.add(key)
        key = normalized_aliases[key]
    return key


def internal_provenance_conflicts(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect geography labels that should never be silently treated as the same slot."""
    out: list[dict[str, Any]] = []
    collection = _canon(metadata.get("collection_location"))
    for field in ("publication_section_label", "analyst_geography"):
        value = _canon(metadata.get(field))
        if collection and value and collection != value:
            out.append(
                {
                    "type": "GEOGRAPHY_SLOT_CONFLICT",
                    "severity": "WARN",
                    "left_field": "collection_location",
                    "left_value": metadata.get("collection_location"),
                    "right_field": field,
                    "right_value": metadata.get(field),
                }
            )
    return out


def compare_provenance(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    text_similarity: float,
    rare_sequence_overlap: float = 0.0,
    alias_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compare source metadata and emit auditable pseudoreplication warnings.

    The detector never claims identity from similarity alone.  It raises a candidate
    when strong textual/rare-sequence overlap co-occurs with provenance reuse or a
    suspicious geography-label mismatch.
    """
    field_deltas: list[dict[str, Any]] = []
    for field in PROVENANCE_FIELDS:
        lv, rv = left.get(field), right.get(field)
        if _canon(lv) != _canon(rv) and (lv not in (None, "") or rv not in (None, "")):
            field_deltas.append({"field": field, "left": lv, "right": rv})

    left_collector = canonical_alias(left.get("collector"), alias_map)
    right_collector = canonical_alias(right.get("collector"), alias_map)
    same_collector = bool(left_collector and right_collector and left_collector == right_collector)
    left_narrator = canonical_alias(left.get("narrator"), alias_map)
    right_narrator = canonical_alias(right.get("narrator"), alias_map)
    same_narrator = bool(left_narrator and right_narrator and left_narrator == right_narrator)

    lc, rc = _canon(left.get("collection_location")), _canon(right.get("collection_location"))
    geography_conflict = bool(lc and rc and lc != rc)
    publication_relabel = False
    for a, b in ((left, right), (right, left)):
        collection = _canon(a.get("collection_location"))
        section = _canon(b.get("publication_section_label"))
        if collection and section and collection != section:
            publication_relabel = True

    alerts: list[dict[str, Any]] = []
    strong_text = text_similarity >= 0.85
    strong_bundle = rare_sequence_overlap >= 0.80
    if strong_text and (same_collector or same_narrator) and (geography_conflict or publication_relabel):
        alerts.append(
            {
                "type": "PSEUDOREPLICATION_ALERT",
                "severity": "HIGH",
                "reason": "high textual overlap + reused provenance identity + geography-label conflict",
            }
        )
    elif strong_text and strong_bundle and (geography_conflict or publication_relabel):
        alerts.append(
            {
                "type": "SAME_OCCURRENCE_CANDIDATE",
                "severity": "MEDIUM",
                "reason": "high textual and rare-sequence overlap with conflicting geography labels",
            }
        )
    elif strong_text and (same_collector or same_narrator):
        alerts.append(
            {
                "type": "TEXTUAL_DEPENDENCE_CANDIDATE",
                "severity": "MEDIUM",
                "reason": "high textual overlap with reused collector/narrator identity",
            }
        )

    return {
        "text_similarity": text_similarity,
        "rare_sequence_overlap": rare_sequence_overlap,
        "same_collector": same_collector,
        "same_narrator": same_narrator,
        "geography_conflict": geography_conflict,
        "publication_relabel": publication_relabel,
        "field_deltas": field_deltas,
        "left_internal_conflicts": internal_provenance_conflicts(left),
        "right_internal_conflicts": internal_provenance_conflicts(right),
        "alerts": alerts,
    }


def slot_mutation_report(left_events: list[dict[str, Any]], right_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Diff semantic event payloads by predicate without changing source text."""
    left = {str(e["predicate"]): e for e in left_events}
    right = {str(e["predicate"]): e for e in right_events}
    retained = sorted(left.keys() & right.keys())
    added = sorted(right.keys() - left.keys())
    removed = sorted(left.keys() - right.keys())
    changed: list[dict[str, Any]] = []
    for predicate in retained:
        lp = left[predicate].get("payload") or {}
        rp = right[predicate].get("payload") or {}
        keys = sorted(set(lp) | set(rp))
        delta = {k: {"left": lp.get(k), "right": rp.get(k)} for k in keys if lp.get(k) != rp.get(k)}
        if delta:
            changed.append({"predicate": predicate, "slot_delta": delta})
    return {"retained": retained, "added": added, "removed": removed, "changed": changed}
