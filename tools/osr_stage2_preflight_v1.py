#!/usr/bin/env python3
"""OSR Stage-2 minimal preflight gate.

Purpose: validate the Stage-1 v3 identity root and a 5-schema real-data canary
before allowing the 1,788-shard Stage-2 Direct Miner to run.

This script intentionally does NOT scan the corpus. It reads the Stage-1 v3
manifest, validates its digest/shape, opens one real shard per schema, reads a
small text sample, performs a deterministic locator -> raw-row SHA round trip,
and writes a resumable VERIFIED sentinel.

Expected to run in Colab after Google Drive is mounted at /content/drive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import pyarrow.parquet as pq
except Exception as exc:
    raise SystemExit("pyarrow is required (available in normal Colab runtimes)") from exc

DRIVE = Path("/content/drive/MyDrive")
WORKSPACE = DRIVE / "OSR_WORK_SPACE"
EXPECTED_SHARDS = 1788
EXPECTED_SOURCE_COUNTS = {"Literature-zh": 233, "ChineseWebText2.0": 1555}
REQUIRED_IDENTITY_FIELDS = (
    "size_bytes",
    "mtime_ns",
    "rows",
    "row_groups",
    "schema_sha256",
)

# Search narrowly first, then fall back to the workspace tree. This is metadata
# traversal only; it never opens corpus payloads during discovery.
MANIFEST_CANDIDATES = [
    WORKSPACE / "Stage1_Outputs_v3" / "manifest_canonical_v3.jsonl",
    WORKSPACE / "Stage1_Outputs" / "manifest_canonical_v3.jsonl",
    WORKSPACE / "Stage1_Outputs_v2" / "manifest_canonical_v3.jsonl",
    WORKSPACE / "manifest_canonical_v3.jsonl",
]
VERIFY_CANDIDATES = [
    WORKSPACE / "Stage1_Outputs_v3" / "STAGE1_V3_VERIFIED.json",
    WORKSPACE / "Stage1_Outputs" / "STAGE1_V3_VERIFIED.json",
    WORKSPACE / "Stage1_Outputs_v2" / "STAGE1_V3_VERIFIED.json",
    WORKSPACE / "STAGE1_V3_VERIFIED.json",
]
PREFLIGHT_DIR = WORKSPACE / "Stage2_Preflight_v1"
SENTINEL = PREFLIGHT_DIR / "STAGE2_PREFLIGHT_VERIFIED.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def first_present(d: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in d and d[name] not in (None, ""):
            return d[name]
    return None


def discover_one(candidates: list[Path], filename: str) -> Path:
    for p in candidates:
        if p.exists():
            return p
    hits = list(WORKSPACE.rglob(filename))
    if len(hits) != 1:
        raise AssertionError(f"expected exactly one {filename}, found {len(hits)}: {hits[:10]}")
    return hits[0]


def load_jsonl(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    raw = path.read_bytes()
    rows = []
    for n, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise AssertionError(f"manifest line {n} is not an object")
        rows.append(obj)
    return raw, rows


def resolve_source(entry: dict[str, Any]) -> str:
    s = str(first_present(entry, "source", "dataset", "corpus") or "")
    sl = s.lower()
    if "literature" in sl:
        return "Literature-zh"
    if "webtext" in sl or "chinesewebtext" in sl:
        return "ChineseWebText2.0"
    return s


def resolve_path(entry: dict[str, Any]) -> Path:
    raw = first_present(entry, "path", "file_path", "filepath", "canonical_path")
    if raw:
        p = Path(str(raw))
        if p.exists():
            return p
        # Handle manifests written with /MyDrive/... or Drive-relative paths.
        text = str(raw)
        for prefix in ("/content/drive/MyDrive/", "MyDrive/", "/MyDrive/"):
            if text.startswith(prefix):
                candidate = DRIVE / text[len(prefix):]
                if candidate.exists():
                    return candidate
    filename = first_present(entry, "filename", "name")
    if not filename:
        raise AssertionError("manifest entry lacks path/filename")
    hits = list(DRIVE.rglob(str(filename)))
    if len(hits) != 1:
        raise AssertionError(f"cannot uniquely resolve {filename}: {len(hits)} hits")
    return hits[0]


def normalize_schema_sha(entry: dict[str, Any]) -> str:
    v = first_present(entry, "schema_sha256", "schema_sha", "schema_hash")
    if not v:
        raise AssertionError("manifest entry missing schema_sha256")
    return str(v)


def edge_fingerprint(path: Path, edge_bytes: int = 1024 * 1024) -> tuple[str, str]:
    size = path.stat().st_size
    with path.open("rb") as f:
        first = f.read(min(edge_bytes, size))
        if size > edge_bytes:
            f.seek(max(0, size - edge_bytes))
        last = f.read(min(edge_bytes, size))
    return sha256_bytes(first), sha256_bytes(last)


def validate_entry_identity(entry: dict[str, Any], path: Path, *, deep_edges: bool) -> dict[str, Any]:
    st = path.stat()
    expected_size = int(first_present(entry, "size_bytes", "bytes", "file_size"))
    expected_mtime = int(first_present(entry, "mtime_ns", "modified_ns", "stat_mtime_ns"))
    assert st.st_size == expected_size, (path, st.st_size, expected_size)
    # Drive FUSE may round timestamps in rare cases; exact match is still the identity contract.
    assert st.st_mtime_ns == expected_mtime, (path, st.st_mtime_ns, expected_mtime)

    pf = pq.ParquetFile(path)
    md = pf.metadata
    expected_rows = int(first_present(entry, "rows", "row_count", "num_rows"))
    expected_rgs = int(first_present(entry, "row_groups", "row_group_count", "num_row_groups"))
    assert md.num_rows == expected_rows, (path, md.num_rows, expected_rows)
    assert md.num_row_groups == expected_rgs, (path, md.num_row_groups, expected_rgs)

    # Recompute schema hash in the two common canonical serializations and require one match.
    expected_schema = normalize_schema_sha(entry)
    schema = pf.schema_arrow
    candidates = {
        sha256_bytes(str(schema).encode("utf-8")),
        sha256_bytes(schema.serialize().to_pybytes()),
    }
    if expected_schema not in candidates:
        # The Stage-1 writer may use a different stable serialization. Do not silently
        # replace its contract: footer still validates, but surface the mismatch.
        raise AssertionError(
            f"schema hash serialization mismatch for {path.name}: expected={expected_schema} candidates={sorted(candidates)}"
        )

    edge = None
    if deep_edges:
        exp_first = first_present(entry, "first_edge_sha256", "edge_first_sha256", "first_sha256")
        exp_last = first_present(entry, "last_edge_sha256", "edge_last_sha256", "last_sha256")
        if exp_first and exp_last:
            got_first, got_last = edge_fingerprint(path)
            assert got_first == str(exp_first), (path, "first-edge", got_first, exp_first)
            assert got_last == str(exp_last), (path, "last-edge", got_last, exp_last)
            edge = {"first": got_first, "last": got_last}

    return {
        "path": str(path),
        "size_bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "rows": md.num_rows,
        "row_groups": md.num_row_groups,
        "schema_sha256": expected_schema,
        "edge": edge,
    }


def text_canary(path: Path) -> dict[str, Any]:
    pf = pq.ParquetFile(path)
    if "text" not in pf.schema_arrow.names:
        raise AssertionError(f"text column missing: {path}")
    table = pf.read_row_group(0, columns=["text"])
    vals = table.column("text").to_pylist()
    idx = next((i for i, x in enumerate(vals) if isinstance(x, str) and x.strip()), None)
    if idx is None:
        raise AssertionError(f"no non-empty text in first row group: {path}")
    raw_text = vals[idx]
    raw_sha = sha256_bytes(raw_text.encode("utf-8"))

    # Deterministic known-hit token derived from the real row itself. Prefer 2-4 CJK
    # chars so this exercises multi-character matching without single-char explosion.
    cjk = re.findall(r"[\u3400-\u9fff]", raw_text)
    token = "".join(cjk[:4]) if len(cjk) >= 2 else raw_text.strip()[:8]
    if not token:
        raise AssertionError(f"cannot derive canary token: {path}")
    assert token in raw_text

    # Rehydrate the same raw row from the source Parquet and verify SHA.
    reread = pf.read_row_group(0, columns=["text"]).column("text")[idx].as_py()
    reread_sha = sha256_bytes(reread.encode("utf-8"))
    assert reread_sha == raw_sha

    return {
        "row_group": 0,
        "row_index_within_group": idx,
        "token": token,
        "raw_text_sha256": raw_sha,
        "rehydrated_sha256": reread_sha,
        "round_trip_ok": True,
    }


def main() -> None:
    manifest_path = discover_one(MANIFEST_CANDIDATES, "manifest_canonical_v3.jsonl")
    verify_path = discover_one(VERIFY_CANDIDATES, "STAGE1_V3_VERIFIED.json")
    verify = json.loads(verify_path.read_text("utf-8"))
    assert bool(first_present(verify, "verified", "stage1_v3_verified")) is True, verify

    raw_manifest, entries = load_jsonl(manifest_path)
    manifest_sha = sha256_bytes(raw_manifest)
    declared_sha = first_present(verify, "manifest_sha256", "canonical_manifest_sha256", "manifest_digest")
    assert declared_sha, "STAGE1_V3_VERIFIED.json lacks manifest_sha256"
    assert manifest_sha == str(declared_sha), (manifest_sha, declared_sha)
    assert len(entries) == EXPECTED_SHARDS, len(entries)

    sources = Counter(resolve_source(e) for e in entries)
    assert sources == Counter(EXPECTED_SOURCE_COUNTS), sources

    # Manifest structural identity checks over all 1,788 entries are cheap and do not
    # open shard payloads.
    for i, e in enumerate(entries):
        missing = [k for k in REQUIRED_IDENTITY_FIELDS if first_present(e, k) is None]
        assert not missing, (i, missing)
        assert first_present(e, "path", "file_path", "filepath", "canonical_path", "filename", "name") is not None

    # Strict ordinal continuity when an ordinal is explicitly present.
    by_source = defaultdict(list)
    for e in entries:
        by_source[resolve_source(e)].append(e)
    expected_ranges = {
        "Literature-zh": set(range(1, 234)),
        "ChineseWebText2.0": set(range(0, 1555)),
    }
    for source, group in by_source.items():
        ords = []
        for e in group:
            v = first_present(e, "ordinal", "shard_ordinal", "index")
            if v is not None:
                ords.append(int(v))
        if ords:
            assert set(ords) == expected_ranges[source], (source, min(ords), max(ords), len(set(ords)))

    # Choose one real shard per schema SHA: exactly five canonical variants are expected.
    schema_groups = defaultdict(list)
    for e in entries:
        schema_groups[normalize_schema_sha(e)].append(e)
    assert len(schema_groups) == 5, f"expected 5 schema variants, found {len(schema_groups)}"

    representatives = []
    for schema_sha, group in sorted(schema_groups.items()):
        e = sorted(group, key=lambda x: str(first_present(x, "filename", "name", "path", "file_path")))[0]
        p = resolve_path(e)
        ident = validate_entry_identity(e, p, deep_edges=True)
        canary = text_canary(p)
        representatives.append({
            "source": resolve_source(e),
            "schema_sha256": schema_sha,
            "identity": ident,
            "canary": canary,
        })

    result = {
        "verified": True,
        "gate": "STAGE2_MINIMAL_PREFLIGHT_V1",
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "stage1_verify_path": str(verify_path),
        "canonical_shards": len(entries),
        "source_counts": dict(sources),
        "schema_variants": len(schema_groups),
        "representatives": representatives,
        "contract": {
            "manifest_root_bound": True,
            "five_schema_real_shards_opened": True,
            "text_only_canary_read": True,
            "raw_row_sha_round_trip": True,
        },
    }

    PREFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SENTINEL.with_suffix(".tmp")
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, SENTINEL)
    # Read-back verifies the Drive artifact itself.
    readback = json.loads(SENTINEL.read_text("utf-8"))
    assert readback["verified"] is True
    assert readback["manifest_sha256"] == manifest_sha

    print("✅ STAGE-2 MINIMAL PREFLIGHT PASS")
    print("manifest_sha256:", manifest_sha)
    print("canonical_shards:", len(entries))
    print("source_counts:", dict(sources))
    print("schema_variants:", len(schema_groups))
    print("sentinel:", SENTINEL)
    print("NEXT: only now run the Stage-2 v3.1 canonical runner.")


if __name__ == "__main__":
    main()
