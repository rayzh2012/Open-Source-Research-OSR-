#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bz2
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq


def lname(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def direct_child(elem: ET.Element, name: str):
    for child in elem:
        if lname(child.tag) == name:
            return child
    return None


def child_text(elem: ET.Element | None, name: str, default: str = '') -> str:
    if elem is None:
        return default
    node = direct_child(elem, name)
    if node is None or node.text is None:
        return default
    return node.text


def as_int(value: str, default: int = -1) -> int:
    try:
        return int(value)
    except Exception:
        return default


def main() -> int:
    ap = argparse.ArgumentParser(description='Stream a Wikimedia current-content XML.bz2 shard into analysis-ready Parquet.')
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--summary-json', required=True)
    ap.add_argument('--wiki-id', required=True)
    ap.add_argument('--dump-date', required=True)
    ap.add_argument('--source-url', required=True)
    ap.add_argument('--source-sha256', required=True)
    ap.add_argument('--batch-size', type=int, default=500)
    args = ap.parse_args()

    src = Path(args.input)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    schema = pa.schema([
        ('wiki_id', pa.string()),
        ('dump_date', pa.string()),
        ('page_id', pa.int64()),
        ('namespace', pa.int32()),
        ('title', pa.string()),
        ('revision_id', pa.int64()),
        ('revision_timestamp', pa.string()),
        ('text', pa.string()),
        ('text_chars', pa.int64()),
        ('text_sha256', pa.string()),
        ('source_filename', pa.string()),
        ('source_url', pa.string()),
        ('source_sha256', pa.string()),
    ])

    writer: pq.ParquetWriter | None = None
    batch: list[dict] = []
    rows = 0
    chars = 0
    namespaces: dict[str, int] = {}

    def flush() -> None:
        nonlocal writer, batch
        if not batch:
            return
        table = pa.Table.from_pylist(batch, schema=schema)
        if writer is None:
            writer = pq.ParquetWriter(
                out,
                schema,
                compression='zstd',
                compression_level=6,
                use_dictionary=['wiki_id', 'dump_date', 'title', 'source_filename'],
                write_statistics=True,
            )
        writer.write_table(table)
        batch = []

    with bz2.open(src, 'rb') as fh:
        for event, elem in ET.iterparse(fh, events=('end',)):
            if lname(elem.tag) != 'page':
                continue

            title = child_text(elem, 'title')
            ns = as_int(child_text(elem, 'ns'), -1)
            page_id = as_int(child_text(elem, 'id'), -1)
            revision = direct_child(elem, 'revision')
            revision_id = as_int(child_text(revision, 'id'), -1)
            timestamp = child_text(revision, 'timestamp')
            text_node = direct_child(revision, 'text') if revision is not None else None
            text = '' if text_node is None or text_node.text is None else text_node.text
            text_bytes = text.encode('utf-8')
            text_hash = hashlib.sha256(text_bytes).hexdigest()

            batch.append({
                'wiki_id': args.wiki_id,
                'dump_date': args.dump_date,
                'page_id': page_id,
                'namespace': ns,
                'title': title,
                'revision_id': revision_id,
                'revision_timestamp': timestamp,
                'text': text,
                'text_chars': len(text),
                'text_sha256': text_hash,
                'source_filename': src.name,
                'source_url': args.source_url,
                'source_sha256': args.source_sha256,
            })
            rows += 1
            chars += len(text)
            namespaces[str(ns)] = namespaces.get(str(ns), 0) + 1

            if len(batch) >= args.batch_size:
                flush()
            elem.clear()

    flush()
    if writer is not None:
        writer.close()
    else:
        pq.write_table(pa.Table.from_pylist([], schema=schema), out, compression='zstd')

    summary = {
        'wiki_id': args.wiki_id,
        'dump_date': args.dump_date,
        'source_filename': src.name,
        'source_url': args.source_url,
        'source_sha256': args.source_sha256,
        'rows': rows,
        'text_chars': chars,
        'namespace_counts': namespaces,
        'parquet_bytes': out.stat().st_size,
        'schema': schema.to_string(),
        'normalizer': 'osr-wikisource-current-v1',
    }
    Path(args.summary_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
