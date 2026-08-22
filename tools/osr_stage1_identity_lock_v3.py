#!/usr/bin/env python3
"""OSR Stage-1 v3 identity lock for the 508GB canonical Parquet corpus.

Purpose:
- discover exactly 233 Literature-zh shards and 1555 ChineseWebText2.0 shards
- validate ordinal continuity
- bind each shard to absolute canonical path, size, mtime, edge fingerprints,
  row count, row-group count, and Arrow schema fingerprint
- emit a canonical JSONL manifest plus a root SHA-256 digest
- emit STAGE1_V3_VERIFIED.json only after every invariant passes

This intentionally avoids full-file hashing of all 508GB. It reads Parquet footers plus
small first/last edge windows. Copy-candidate full-file duplicate verification belongs to
acquisition cleanup, not this lock step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

VERSION = "osr-stage1-identity-lock-v3.1"
EDGE_BYTES = 1024 * 1024
EXPECTED = {
    "Literature-zh": 233,
    "ChineseWebText2.0-HighQuality": 1555,
}

LIT_RE = re.compile(r"literature_zh-(\d{5})-of-00233\.parquet$")
WEB_RE = re.compile(r"CASIA-LM_ChineseWebText2\.0_partial-(\d{6})\.parquet$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def edge_sha256(path: Path, edge_bytes: int = EDGE_BYTES) -> Tuple[str, str]:
    size = path.stat().st_size
    with path.open("rb") as f:
        first = f.read(edge_bytes)
        if size > edge_bytes:
            f.seek(max(0, size - edge_bytes))
            last = f.read(edge_bytes)
        else:
            last = first
    return sha256_bytes(first), sha256_bytes(last)


def schema_sha256(schema: pa.Schema) -> str:
    return sha256_bytes(schema.serialize().to_pybytes())


def find_unique_dir(root: Path, name: str) -> Path:
    direct = root / name
    if direct.is_dir():
        return direct
    matches: List[Path] = []
    for base, dirs, _files in os.walk(root):
        if name in dirs:
            matches.append(Path(base) / name)
            dirs[:] = [d for d in dirs if d != name]
        if len(matches) > 1:
            break
    if not matches:
        raise FileNotFoundError(f"Cannot find corpus folder {name!r} under {root}")
    if len(matches) != 1:
        raise RuntimeError(f"Corpus folder {name!r} is ambiguous under {root}: {matches}")
    return matches[0]


def list_source_files(source: str, folder: Path) -> List[Tuple[int, Path]]:
    pairs: List[Tuple[int, Path]] = []
    for path in folder.rglob("*.parquet"):
        name = path.name
        m = LIT_RE.match(name) if source == "Literature-zh" else WEB_RE.match(name)
        if m:
            pairs.append((int(m.group(1)), path))
    pairs.sort(key=lambda x: x[0])
    return pairs


def expected_ordinals(source: str) -> List[int]:
    if source == "Literature-zh":
        return list(range(1, 234))
    return list(range(0, 1555))


def inspect_shard(source: str, ordinal: int, path: Path, source_root: Path) -> dict:
    st = path.stat()
    pf = pq.ParquetFile(path)
    md = pf.metadata
    first_sha, last_sha = edge_sha256(path)
    ssha = schema_sha256(pf.schema_arrow)
    rec = {
        "identity_version": VERSION,
        "source": source,
        "ordinal": ordinal,
        "filename": path.name,
        "canonical_path": str(path),
        "relative_path": str(path.relative_to(source_root)),
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "first_edge_sha256": first_sha,
        "last_edge_sha256": last_sha,
        "rows": int(md.num_rows),
        "row_groups": int(md.num_row_groups),
        "schema_sha256": ssha,
    }
    sig_fields = {
        k: rec[k]
        for k in (
            "source", "ordinal", "filename", "canonical_path", "relative_path",
            "size_bytes", "mtime_ns", "first_edge_sha256", "last_edge_sha256",
            "rows", "row_groups", "schema_sha256"
        )
    }
    rec["source_signature_sha256"] = sha256_bytes(canonical_json(sig_fields))
    return rec


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    if sha256_bytes(tmp.read_bytes()) != sha256_bytes(data):
        raise IOError(f"Read-back verification failed for {tmp}")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive-root", default="/content/drive/MyDrive")
    ap.add_argument("--literature-dir-name", default="Literature-zh_229GB")
    ap.add_argument("--webtext-dir-name", default="ChineseWebText2.0-HighQuality_279GB")
    ap.add_argument("--out-dir", default="/content/drive/MyDrive/OSR_WORK_SPACE/Stage1_Identity_v3")
    ap.add_argument("--progress-every", type=int, default=25)
    args = ap.parse_args()

    drive_root = Path(args.drive_root)
    out_dir = Path(args.out_dir)
    if not drive_root.is_dir():
        raise FileNotFoundError(f"Drive root not mounted: {drive_root}")

    roots = {
        "Literature-zh": find_unique_dir(drive_root, args.literature_dir_name),
        "ChineseWebText2.0-HighQuality": find_unique_dir(drive_root, args.webtext_dir_name),
    }
    print("Resolved corpus roots:")
    for k, v in roots.items():
        print(f"  {k}: {v}")

    inventories: Dict[str, List[Tuple[int, Path]]] = {}
    for source, root in roots.items():
        pairs = list_source_files(source, root)
        got = [o for o, _ in pairs]
        exp = expected_ordinals(source)
        if got != exp:
            missing = sorted(set(exp) - set(got))[:20]
            extra = sorted(set(got) - set(exp))[:20]
            raise RuntimeError(
                f"{source}: ordinal continuity failed; count={len(got)} expected={len(exp)} "
                f"missing(sample)={missing} extra(sample)={extra}"
            )
        if len(pairs) != EXPECTED[source]:
            raise RuntimeError(f"{source}: shard count {len(pairs)} != {EXPECTED[source]}")
        inventories[source] = pairs
        print(f"✅ {source}: {len(pairs)} canonical shards with continuous ordinals")

    records: List[dict] = []
    total = sum(len(v) for v in inventories.values())
    done = 0
    t0 = time.time()
    schema_counts: Dict[str, int] = {}
    source_rows: Dict[str, int] = {k: 0 for k in inventories}

    for source in ("Literature-zh", "ChineseWebText2.0-HighQuality"):
        root = roots[source]
        for ordinal, path in inventories[source]:
            rec = inspect_shard(source, ordinal, path, root)
            records.append(rec)
            schema_counts[rec["schema_sha256"]] = schema_counts.get(rec["schema_sha256"], 0) + 1
            source_rows[source] += rec["rows"]
            done += 1
            if done % args.progress_every == 0 or done == total:
                elapsed = time.time() - t0
                print(f"[{done}/{total}] identity locked; elapsed={elapsed:.1f}s last={path.name}")

    if len(records) != 1788:
        raise RuntimeError(f"Canonical record count {len(records)} != 1788")
    if len(schema_counts) != 5:
        raise RuntimeError(f"Observed schema fingerprint count {len(schema_counts)} != expected 5: {schema_counts}")

    records.sort(key=lambda r: (r["source"], r["ordinal"]))
    manifest_bytes = b"".join(canonical_json(r) for r in records)
    manifest_sha = sha256_bytes(manifest_bytes)
    manifest_path = out_dir / "manifest_canonical_v3.jsonl"
    write_atomic(manifest_path, manifest_bytes)

    final_sha = sha256_bytes(manifest_path.read_bytes())
    if final_sha != manifest_sha:
        raise IOError(f"Final manifest SHA mismatch: {final_sha} != {manifest_sha}")

    verified = {
        "verified": True,
        "identity_version": VERSION,
        "manifest_file": manifest_path.name,
        "manifest_sha256": manifest_sha,
        "canonical_shards": 1788,
        "source_shards": {k: len(v) for k, v in inventories.items()},
        "source_rows": source_rows,
        "schema_fingerprint_count": len(schema_counts),
        "schema_counts": dict(sorted(schema_counts.items())),
        "edge_bytes": EDGE_BYTES,
        "corpus_roots": {k: str(v) for k, v in roots.items()},
        "stage2_next_allowed": True,
        "generated_unix": time.time(),
    }
    verified_path = out_dir / "STAGE1_V3_VERIFIED.json"
    write_atomic(verified_path, json.dumps(verified, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")

    print("\n✅ STAGE1 V3 IDENTITY LOCK VERIFIED")
    print("manifest:", manifest_path)
    print("manifest_sha256:", manifest_sha)
    print("verified:", verified_path)
    print("schemas:", len(schema_counts))
    print("rows:", source_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
