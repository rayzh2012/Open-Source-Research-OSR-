from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .core import KeywordAutomaton, normalize_text, sha256_text, stable_json


LEGACY_OUTPUT_VERSION = "legacy-output/v1"
EXPLICIT_LABELS = (
    "FACT",
    "LOCK",
    "CANON",
    "HYPOTHESIS",
    "STRONG_INFERENCE",
    "CONTRADICTION",
    "TODO",
    "OPEN",
    "REJECTED",
)
_LABEL_RE = re.compile(r"(?i)(?:^|[\s\[【(（:_-])(FACT|LOCK|CANON|HYPOTHESIS|STRONG_INFERENCE|CONTRADICTION|TODO|OPEN|REJECTED)(?:$|[\s\]】)）:_-])")


def split_output_blocks(text: str) -> list[str]:
    """Split Markdown/plain-text outputs into stable review-sized blocks.

    Headings are kept as independent blocks and blank lines terminate paragraphs.
    This is deliberately simple and deterministic so old exports can be re-scanned
    identically without an LLM.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            value = normalize_text("\n".join(current))
            if value:
                blocks.append(value)
            current.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            blocks.append(normalize_text(stripped))
            continue
        current.append(line)
    flush()
    return blocks


def classify_block(block: str) -> list[str]:
    labels = sorted({m.group(1).upper() for m in _LABEL_RE.finditer(block)})
    return labels or ["IDEA_CANDIDATE"]


def dictionary_hits(block: str, terms: Iterable[str]) -> list[str]:
    automaton = KeywordAutomaton(terms)
    return sorted({term for _, term in automaton.scan(block)})


def build_legacy_record(
    *,
    source: dict[str, Any],
    text: str,
    dictionary: Iterable[str] = (),
) -> dict[str, Any]:
    """Convert one historical AI/user output into a content-addressed review record.

    Critical epistemic rule: legacy outputs are analyst artifacts, never primary
    witnesses. Nothing in this function upgrades an old claim into source evidence.
    """
    norm = normalize_text(text)
    output_hash = sha256_text(norm)
    source_record = dict(source)
    source_record.setdefault("artifact_kind", "ANALYST_OUTPUT")
    source_record.setdefault("epistemic_status", "UNVERIFIED_LEGACY_OUTPUT")
    source_record["legacy_output_version"] = LEGACY_OUTPUT_VERSION
    output_id = sha256_text(output_hash + "|" + stable_json(source_record))
    terms = list(dictionary)

    blocks: list[dict[str, Any]] = []
    for ordinal, block in enumerate(split_output_blocks(text)):
        block_hash = sha256_text(block)
        blocks.append(
            {
                "block_id": sha256_text(output_id + f"|{ordinal}|" + block_hash),
                "ordinal": ordinal,
                "block_hash": block_hash,
                "labels": classify_block(block),
                "dictionary_hits": dictionary_hits(block, terms) if terms else [],
                "text": block,
                "epistemic_status": "UNVERIFIED_LEGACY_OUTPUT",
            }
        )

    return {
        "legacy_output_version": LEGACY_OUTPUT_VERSION,
        "output_id": output_id,
        "output_hash": output_hash,
        "source": source_record,
        "block_count": len(blocks),
        "blocks": blocks,
    }


def write_legacy_bundle(record: dict[str, Any], output_dir: str | Path, *, include_text: bool = True) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "legacy_output_version": record["legacy_output_version"],
        "output_id": record["output_id"],
        "output_hash": record["output_hash"],
        "block_count": record["block_count"],
        "source": record["source"],
        "text_included": bool(include_text),
        "epistemic_guard": "ANALYST_OUTPUT_NEVER_COUNTS_AS_PRIMARY_SOURCE",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with (root / "blocks.jsonl").open("w", encoding="utf-8") as fh:
        for block in record["blocks"]:
            row = dict(block)
            if not include_text:
                row.pop("text", None)
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return root


def scan_export_directory(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    dictionary: Iterable[str] = (),
    include_text: bool = True,
    suffixes: tuple[str, ...] = (".md", ".txt"),
) -> list[dict[str, Any]]:
    """Batch-scan exported historical outputs into deterministic legacy bundles."""
    src_root = Path(input_dir)
    out_root = Path(output_dir)
    rows: list[dict[str, Any]] = []
    files = sorted(p for p in src_root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)
    for path in files:
        rel = path.relative_to(src_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        record = build_legacy_record(
            source={"source_path": rel, "source_type": "LEGACY_EXPORT"},
            text=text,
            dictionary=dictionary,
        )
        bundle = out_root / record["output_id"][:16]
        write_legacy_bundle(record, bundle, include_text=include_text)
        rows.append(
            {
                "source_path": rel,
                "output_id": record["output_id"],
                "output_hash": record["output_hash"],
                "block_count": record["block_count"],
                "bundle_path": str(bundle),
            }
        )
    out_root.mkdir(parents=True, exist_ok=True)
    with (out_root / "LEGACY_INDEX.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan exported historical research outputs into Myth Engine legacy bundles.")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--term", action="append", default=[], help="Deterministic dictionary term; repeatable")
    parser.add_argument("--hash-only", action="store_true", help="Do not include block text in generated bundles")
    args = parser.parse_args(argv)
    rows = scan_export_directory(
        args.input_dir,
        args.output_dir,
        dictionary=args.term,
        include_text=not args.hash_only,
    )
    print(json.dumps({"files": len(rows), "blocks": sum(r["block_count"] for r in rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
