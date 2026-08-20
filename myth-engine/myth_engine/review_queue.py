from __future__ import annotations

from typing import Any

from .core import MythDB
from .fingerprint_index import search_fingerprint_candidates


def build_legacy_review_queue(
    db: MythDB,
    legacy_record: dict[str, Any],
    *,
    min_score: float = 0.12,
    limit_per_block: int = 5,
) -> list[dict[str, Any]]:
    """Route old analyst-output blocks toward current source-corpus candidates.

    This is a candidate generator only. Textual similarity does not prove support or
    contradiction, so every row remains UNRESOLVED until a separate audited decision
    links the legacy claim to source evidence.
    """
    queue: list[dict[str, Any]] = []
    for block in legacy_record.get("blocks", []):
        text = block.get("text", "")
        candidates = [
            item
            for item in search_fingerprint_candidates(db, text, limit=limit_per_block)
            if float(item["fingerprint_jaccard"]) >= min_score
        ]
        queue.append(
            {
                "output_id": legacy_record.get("output_id"),
                "block_id": block.get("block_id"),
                "block_ordinal": block.get("ordinal"),
                "legacy_labels": block.get("labels", []),
                "legacy_epistemic_status": block.get("epistemic_status", "UNVERIFIED_LEGACY_OUTPUT"),
                "resolution_status": "UNRESOLVED_CANDIDATES" if candidates else "UNRESOLVED_NO_MATCH",
                "candidate_segments": candidates,
                "guard": "TEXT_SIMILARITY_IS_NOT_EVIDENCE_VERDICT",
            }
        )
    return queue


def apply_audited_resolution(
    queue_item: dict[str, Any],
    *,
    verdict: str,
    evidence_segment_ids: list[str],
    reviewer: str,
    note: str = "",
) -> dict[str, Any]:
    """Attach an explicit human/AI-audited evidence verdict after source review."""
    allowed = {"SUPPORTED", "CONTRADICTED", "PARTLY_SUPPORTED", "UNRESOLVED"}
    if verdict not in allowed:
        raise ValueError(f"invalid verdict: {verdict}")
    if verdict != "UNRESOLVED" and not evidence_segment_ids:
        raise ValueError("resolved verdict requires evidence_segment_ids")
    out = dict(queue_item)
    out["resolution_status"] = verdict
    out["evidence_segment_ids"] = list(evidence_segment_ids)
    out["reviewer"] = reviewer
    out["resolution_note"] = note
    out["resolution_guard"] = "VERDICT_REQUIRES_EXPLICIT_SOURCE_SEGMENT_LINK"
    return out
