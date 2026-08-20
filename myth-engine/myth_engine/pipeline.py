from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .core import MythDB, merkle_root, normalize_text, paragraphs, sha256_text, stable_json


BUNDLE_VERSION = "witness-bundle/v1"


def _json_dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _jsonl_dump(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(stable_json(row) + "\n")


def build_witness_bundle(
    *,
    source: dict[str, Any],
    text: str,
    output_dir: str | Path,
    include_raw: bool = False,
    semantic_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, content-addressed witness artifact bundle.

    The function is intentionally filesystem-only. Large/private source files remain
    in Drive or local storage; this bundle holds text derivatives and hashes. For a
    public Git working tree, keep include_raw=False unless redistribution is allowed.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    normalized = normalize_text(text)
    parts = paragraphs(text)
    segment_rows: list[dict[str, Any]] = []
    segment_hashes: list[str] = []
    for ordinal, part in enumerate(parts):
        norm = normalize_text(part)
        segment_hash = sha256_text(norm)
        segment_hashes.append(segment_hash)
        segment_rows.append(
            {
                "ordinal": ordinal,
                "segment_hash": segment_hash,
                "text": norm,
            }
        )

    source_record = dict(source)
    source_record["bundle_version"] = BUNDLE_VERSION
    source_record["raw_source_committed"] = bool(include_raw)

    doc_hash = sha256_text(normalized)
    root = merkle_root(segment_hashes)
    witness_key = sha256_text(doc_hash + "|" + stable_json(source_record))

    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "witness_key": witness_key,
        "doc_hash": doc_hash,
        "merkle_root": root,
        "segment_count": len(segment_rows),
        "normalized_size_chars": len(normalized),
        "raw_included": bool(include_raw),
        "semantic_events_included": bool(semantic_events),
        "artifacts": {
            "source": "source.json",
            "normalized": "normalized.txt",
            "segments": "segments.jsonl",
            "raw": "raw.txt" if include_raw else None,
            "semantic_events": "semantic-events.jsonl" if semantic_events else None,
        },
    }

    _json_dump(out / "source.json", source_record)
    (out / "normalized.txt").write_text(normalized + "\n", encoding="utf-8")
    _jsonl_dump(out / "segments.jsonl", segment_rows)
    _json_dump(out / "manifest.json", manifest)
    if include_raw:
        (out / "raw.txt").write_text(text, encoding="utf-8")
    if semantic_events:
        _jsonl_dump(out / "semantic-events.jsonl", semantic_events)

    return manifest


def load_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    root = Path(bundle_dir)
    return {
        "root": root,
        "manifest": json.loads((root / "manifest.json").read_text(encoding="utf-8")),
        "source": json.loads((root / "source.json").read_text(encoding="utf-8")),
        "normalized": (root / "normalized.txt").read_text(encoding="utf-8").rstrip("\n"),
    }


def verify_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    bundle = load_bundle(bundle_dir)
    root: Path = bundle["root"]
    manifest = bundle["manifest"]
    source = bundle["source"]
    normalized = bundle["normalized"]

    segment_rows = [json.loads(line) for line in (root / "segments.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []

    if manifest.get("bundle_version") != BUNDLE_VERSION:
        errors.append("bundle_version_mismatch")
    if source.get("bundle_version") != BUNDLE_VERSION:
        errors.append("source_bundle_version_mismatch")
    if sha256_text(normalized) != manifest.get("doc_hash"):
        errors.append("doc_hash_mismatch")
    if len(segment_rows) != manifest.get("segment_count"):
        errors.append("segment_count_mismatch")

    hashes: list[str] = []
    reconstructed: list[str] = []
    for expected_ordinal, row in enumerate(segment_rows):
        if row.get("ordinal") != expected_ordinal:
            errors.append(f"segment_ordinal_mismatch:{expected_ordinal}")
        text = normalize_text(row.get("text", ""))
        actual_hash = sha256_text(text)
        if actual_hash != row.get("segment_hash"):
            errors.append(f"segment_hash_mismatch:{expected_ordinal}")
        hashes.append(actual_hash)
        reconstructed.append(text)

    if merkle_root(hashes) != manifest.get("merkle_root"):
        errors.append("merkle_root_mismatch")
    if normalize_text(" ".join(reconstructed)) != normalized:
        errors.append("normalized_reconstruction_mismatch")

    expected_witness_key = sha256_text(manifest.get("doc_hash", "") + "|" + stable_json(source))
    if expected_witness_key != manifest.get("witness_key"):
        errors.append("witness_key_mismatch")

    return {
        "ok": not errors,
        "errors": errors,
        "witness_key": manifest.get("witness_key"),
        "segment_count": len(segment_rows),
    }


def ingest_bundle(db: MythDB, bundle_dir: str | Path) -> str:
    verification = verify_bundle(bundle_dir)
    if not verification["ok"]:
        raise ValueError("invalid witness bundle: " + ", ".join(verification["errors"]))
    bundle = load_bundle(bundle_dir)
    metadata = dict(bundle["source"])
    metadata["artifact_witness_key"] = bundle["manifest"]["witness_key"]
    metadata["artifact_merkle_root"] = bundle["manifest"]["merkle_root"]
    return db.add_witness(metadata, bundle["normalized"])


def batch_ingest(db: MythDB, root_dir: str | Path) -> list[tuple[str, str]]:
    """Ingest every valid witness bundle below root_dir in path order."""
    root = Path(root_dir)
    out: list[tuple[str, str]] = []
    for manifest_path in sorted(root.rglob("manifest.json")):
        bundle_dir = manifest_path.parent
        wid = ingest_bundle(db, bundle_dir)
        out.append((str(bundle_dir), wid))
    return out
