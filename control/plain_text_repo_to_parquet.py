#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_catalog(root: Path) -> dict[str, dict]:
    catalog = root / 'catalog.csv'
    if not catalog.exists():
        return {}
    rows = {}
    with catalog.open('r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            key = (row.get('path') or '').strip().replace('\\', '/')
            if key:
                rows[key] = row
            rid = (row.get('id') or '').strip()
            if rid:
                rows.setdefault(rid, row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--source-id', required=True)
    ap.add_argument('--source-repo', required=True)
    ap.add_argument('--source-commit', required=True)
    ap.add_argument('--license', required=True)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(root)

    schema = pa.schema([
        ('source_id', pa.string()),
        ('source_repo', pa.string()),
        ('source_commit', pa.string()),
        ('license', pa.string()),
        ('path', pa.string()),
        ('doc_id', pa.string()),
        ('title', pa.string()),
        ('byline', pa.string()),
        ('era', pa.string()),
        ('category', pa.string()),
        ('text', pa.string()),
        ('text_chars', pa.int64()),
        ('text_sha256', pa.string()),
    ])

    writer = None
    rows = []
    count = 0
    chars = 0

    def flush() -> None:
        nonlocal writer, rows
        if not rows:
            return
        table = pa.Table.from_pylist(rows, schema=schema)
        if writer is None:
            writer = pq.ParquetWriter(out, schema, compression='zstd', compression_level=6, write_statistics=True)
        writer.write_table(table)
        rows = []

    for path in sorted(root.rglob('*.txt')):
        if '.git' in path.parts:
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('utf-8', errors='replace')
        rel = path.relative_to(root).as_posix()
        meta = catalog.get(rel) or catalog.get(path.stem) or {}
        title = (meta.get('title') or path.stem).strip()
        byline = (meta.get('byline') or meta.get('author') or '').strip()
        era = (meta.get('era') or meta.get('date_ca') or '').strip()
        category = (meta.get('group') or meta.get('orig_category') or meta.get('subcat_name') or meta.get('subcat') or '').strip()
        doc_id = (meta.get('id') or path.stem).strip()
        rows.append({
            'source_id': args.source_id,
            'source_repo': args.source_repo,
            'source_commit': args.source_commit,
            'license': args.license,
            'path': rel,
            'doc_id': doc_id,
            'title': title,
            'byline': byline,
            'era': era,
            'category': category,
            'text': text,
            'text_chars': len(text),
            'text_sha256': sha256_bytes(text.encode('utf-8')),
        })
        count += 1
        chars += len(text)
        if len(rows) >= 256:
            flush()

    flush()
    if writer is not None:
        writer.close()
    else:
        pq.write_table(pa.Table.from_pylist([], schema=schema), out, compression='zstd')

    summary = {
        'source_id': args.source_id,
        'source_repo': args.source_repo,
        'source_commit': args.source_commit,
        'documents': count,
        'text_chars': chars,
        'parquet_bytes': out.stat().st_size,
        'schema': schema.to_string(),
        'normalizer': 'osr-plain-text-repo-v1',
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
