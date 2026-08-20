from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from typing import Any


ARCHIVE_MANIFEST_COLUMNS = ("source_id", "url", "filename")
ARCHIVE_RESULT_COLUMNS = ("source_id", "status", "filename", "size_bytes", "sha256", "source_url")


def _parse_tsv(text: str, required: tuple[str, ...]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if reader.fieldnames is None:
        raise ValueError("missing TSV header")
    missing = [c for c in required if c not in reader.fieldnames]
    if missing:
        raise ValueError("missing TSV columns: " + ", ".join(missing))
    rows: list[dict[str, str]] = []
    for row in reader:
        clean = {k: (v or "").strip() for k, v in row.items() if k is not None}
        if any(clean.values()):
            rows.append(clean)
    return rows


def parse_archive_manifest(text: str) -> list[dict[str, str]]:
    rows = _parse_tsv(text, ARCHIVE_MANIFEST_COLUMNS)
    seen: set[str] = set()
    for row in rows:
        sid = row["source_id"]
        if not sid:
            raise ValueError("empty source_id in archive manifest")
        if sid in seen:
            raise ValueError(f"duplicate source_id in archive manifest: {sid}")
        seen.add(sid)
    return rows


def parse_archive_results(text: str) -> dict[str, dict[str, str]]:
    rows = _parse_tsv(text, ARCHIVE_RESULT_COLUMNS)
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        sid = row["source_id"]
        if not sid:
            raise ValueError("empty source_id in archive results")
        if sid in out:
            raise ValueError(f"duplicate source_id in archive results: {sid}")
        out[sid] = row
    return out


def join_archive_records(manifest_text: str, results_text: str | None = None) -> list[dict[str, Any]]:
    """Join acquisition intent with workflow results without inventing missing success.

    A manifest row with no result remains FETCH_NOT_RUN_OR_RESULT_MISSING. Only an
    explicit OK_PDF row is promoted to ACQUIRED_VERIFIED_BY_BRIDGE.
    """
    manifest = parse_archive_manifest(manifest_text)
    results = parse_archive_results(results_text) if results_text is not None else {}
    records: list[dict[str, Any]] = []
    for item in manifest:
        result = results.get(item["source_id"])
        record: dict[str, Any] = {
            "archive_bridge_schema": "archive-fetch-bridge/v1",
            "source_id": item["source_id"],
            "source_url": item["url"],
            "filename": item["filename"],
            "acquisition_status": "FETCH_NOT_RUN_OR_RESULT_MISSING",
            "source_sha256": None,
            "source_size_bytes": None,
        }
        if result is not None:
            if result["filename"] and result["filename"] != item["filename"]:
                record["result_filename_conflict"] = {
                    "manifest": item["filename"],
                    "result": result["filename"],
                }
            if result["source_url"] and result["source_url"] != item["url"]:
                record["result_url_conflict"] = {
                    "manifest": item["url"],
                    "result": result["source_url"],
                }
            record["bridge_status"] = result["status"]
            if result["status"] == "OK_PDF":
                if not result["sha256"]:
                    raise ValueError(f"OK_PDF without sha256: {item['source_id']}")
                record["acquisition_status"] = "ACQUIRED_VERIFIED_BY_BRIDGE"
                record["source_sha256"] = result["sha256"]
                record["source_size_bytes"] = int(result["size_bytes"]) if result["size_bytes"] else None
            else:
                record["acquisition_status"] = result["status"] or "UNKNOWN_BRIDGE_STATUS"
        records.append(record)
    return records


def source_stub(record: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Build source.json-ready metadata; no source body is copied into Git."""
    out = dict(record)
    out.update(extra)
    out.setdefault("raw_source_committed", False)
    out.setdefault("source_layer", "ARCHIVE_SOURCE")
    return out


def write_source_stubs(records: list[dict[str, Any]], output_dir: str | Path) -> list[Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in sorted(records, key=lambda x: str(x.get("source_id", ""))):
        sid = str(record.get("source_id", "")).strip()
        if not sid:
            raise ValueError("source record missing source_id")
        dest = root / sid / "source.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(source_stub(record), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        written.append(dest)
    return written


def write_records_jsonl(records: list[dict[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        for row in sorted(records, key=lambda x: str(x.get("source_id", ""))):
            fh.write(json.dumps(source_stub(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge archive-fetch TSV output into Myth Engine source metadata.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("--stubs-dir", type=Path, required=True)
    parser.add_argument("--records-jsonl", type=Path)
    args = parser.parse_args(argv)

    records = join_archive_records(
        args.manifest.read_text(encoding="utf-8"),
        args.results.read_text(encoding="utf-8"),
    )
    paths = write_source_stubs(records, args.stubs_dir)
    if args.records_jsonl:
        write_records_jsonl(records, args.records_jsonl)
    ok = sum(1 for row in records if row["acquisition_status"] == "ACQUIRED_VERIFIED_BY_BRIDGE")
    print(json.dumps({"records": len(records), "verified": ok, "source_stubs": len(paths)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
