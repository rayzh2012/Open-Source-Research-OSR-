from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import MythDB


def load_fixture(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _event_rows(db: MythDB, witness_id: str, semantic_version: str) -> list[dict[str, Any]]:
    rows = [
        r
        for r in db.search_events(semantic_version=semantic_version)
        if r["witness_id"] == witness_id
    ]
    rows.sort(key=lambda r: (r["ordinal"], r["predicate"], r["event_id"]))
    for r in rows:
        r["tags"] = json.loads(r.pop("tags_json"))
        r["payload"] = json.loads(r.pop("payload_json"))
        r["state_before_obj"] = json.loads(r["state_before"])
        r["state_after_obj"] = json.loads(r["state_after"])
    return rows


def ingest_fixture(db: MythDB, fixture: dict[str, Any]) -> tuple[str, list[str]]:
    """Ingest a small public-safe benchmark fixture.

    Real copyrighted source text stays in the private Drive/archive layer. The
    repository fixture contains source metadata, derived test text, and a human-
    audited semantic gold sequence so CI can test the engine without copying a
    source book into Git.
    """
    semver = fixture["semantic_version"]
    db.add_semantic_version(
        semver,
        fixture.get("semantic_config", {"fixture": "manual-gold"}),
        description=fixture.get("semantic_description", "public-safe manual benchmark"),
    )

    metadata = dict(fixture["source"])
    metadata.update(
        {
            "fixture_id": fixture["fixture_id"],
            "fixture_kind": "DERIVED_PUBLIC_SAFE_BENCHMARK",
            "raw_source_committed": False,
        }
    )
    text = "\n\n".join(fixture["derived_test_segments"])
    witness_id = db.add_witness(metadata, text)

    segment_rows = db.db.execute(
        "SELECT ordinal, segment_id FROM segment WHERE witness_id=? ORDER BY ordinal",
        (witness_id,),
    ).fetchall()
    segment_by_ordinal = {r["ordinal"]: r["segment_id"] for r in segment_rows}

    event_ids: list[str] = []
    for event in fixture["events"]:
        segment_ordinal = event.get("segment_ordinal")
        segment_id = segment_by_ordinal.get(segment_ordinal) if segment_ordinal is not None else None
        event_ids.append(
            db.add_event(
                witness_id=witness_id,
                semantic_version=semver,
                ordinal=event["ordinal"],
                predicate=event["predicate"],
                actor=event.get("actor"),
                patient=event.get("patient"),
                segment_id=segment_id,
                state_before=event.get("state_before"),
                state_after=event.get("state_after"),
                tags=event.get("tags"),
                payload=event.get("payload"),
            )
        )

    for left, right in zip(event_ids, event_ids[1:]):
        db.add_edge(
            left,
            right,
            "NEXT_EVENT",
            provenance={"fixture_id": fixture["fixture_id"], "semantic_version": semver},
        )
    return witness_id, event_ids


def semantic_diff(db: MythDB, left: str, right: str, semantic_version: str) -> dict[str, Any]:
    """Deterministic event/slot diff; no embeddings and no model similarity."""
    left_rows = _event_rows(db, left, semantic_version)
    right_rows = _event_rows(db, right, semantic_version)

    def keyed(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
        seen: dict[str, int] = {}
        out: dict[tuple[str, int], dict[str, Any]] = {}
        for row in rows:
            predicate = row["predicate"]
            occurrence = seen.get(predicate, 0)
            seen[predicate] = occurrence + 1
            out[(predicate, occurrence)] = row
        return out

    a = keyed(left_rows)
    b = keyed(right_rows)
    ak, bk = set(a), set(b)
    common = sorted(ak & bk)
    added = sorted(bk - ak)
    removed = sorted(ak - bk)
    changed: list[dict[str, Any]] = []

    for key in common:
        la, rb = a[key], b[key]
        delta: dict[str, Any] = {}
        for field in ("actor", "patient", "tags", "payload", "state_before_obj", "state_after_obj"):
            if la.get(field) != rb.get(field):
                delta[field] = {"left": la.get(field), "right": rb.get(field)}
        if delta:
            changed.append(
                {
                    "predicate": key[0],
                    "occurrence": key[1],
                    "delta": delta,
                }
            )

    return {
        "left": left,
        "right": right,
        "semantic_version": semantic_version,
        "retained": [k[0] for k in common],
        "added": [k[0] for k in added],
        "removed": [k[0] for k in removed],
        "changed": changed,
    }


def compare_fixture_pair(db: MythDB, left: str, right: str, semantic_version: str) -> dict[str, Any]:
    return {
        "text": db.compare_witnesses(left, right),
        "semantic": semantic_diff(db, left, right, semantic_version),
    }
