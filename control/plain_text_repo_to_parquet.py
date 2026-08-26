#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SUPPORTED = {'.txt', '.xml', '.json', '.conllu', '.conll'}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_catalog(root: Path) -> dict[str, dict]:
    candidates = [root / 'catalog.csv', root / 'catalog' / 'catalog.csv']
    catalog = next((p for p in candidates if p.exists()), None)
    if catalog is None:
        return {}
    rows: dict[str, dict] = {}
    with catalog.open('r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            for field in ('path', 'file', 'filename', 'source_filename'):
                key = (row.get(field) or '').strip().replace('\\', '/')
                if key:
                    rows.setdefault(key, row)
                    rows.setdefault(Path(key).name, row)
                    rows.setdefault(Path(key).stem, row)
            rid = (row.get('id') or row.get('doc_id') or row.get('catalog_no') or '').strip()
            if rid:
                rows.setdefault(rid, row)
    return rows


def collapse_ws(text: str) -> str:
    return re.sub(r'[ \t\r\f\v]+', ' ', text).strip()


def parse_txt(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    try:
        return raw.decode('utf-8'), ''
    except UnicodeDecodeError:
        return raw.decode('utf-8', errors='replace'), ''


def first_local(root: ET.Element, names: set[str]) -> str:
    for elem in root.iter():
        local = elem.tag.rsplit('}', 1)[-1].lower() if isinstance(elem.tag, str) else ''
        if local in names:
            text = collapse_ws(''.join(elem.itertext()))
            if text:
                return text
    return ''


def parse_xml(path: Path) -> tuple[str, str]:
    try:
        root = ET.parse(path).getroot()
    except Exception:
        raw = path.read_bytes()
        return raw.decode('utf-8', errors='replace'), ''
    title = first_local(root, {'title'})
    body = None
    for elem in root.iter():
        local = elem.tag.rsplit('}', 1)[-1].lower() if isinstance(elem.tag, str) else ''
        if local == 'body':
            body = elem
            break
    target = body if body is not None else root
    chunks = []
    for text in target.itertext():
        t = collapse_ws(text)
        if t:
            chunks.append(t)
    return '\n'.join(chunks), title


def collect_json_strings(obj, out: list[str]) -> None:
    if isinstance(obj, str):
        s = obj.strip()
        if s:
            out.append(s)
    elif isinstance(obj, dict):
        for value in obj.values():
            collect_json_strings(value, out)
    elif isinstance(obj, list):
        for value in obj:
            collect_json_strings(value, out)


def parse_json(path: Path) -> tuple[str, str]:
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return path.read_text(encoding='utf-8', errors='replace'), ''
    strings: list[str] = []
    collect_json_strings(obj, strings)
    return '\n'.join(strings), ''


def parse_conllu(path: Path) -> tuple[str, str]:
    sentences: list[str] = []
    tokens: list[str] = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            if tokens:
                sentences.append(' '.join(tokens))
                tokens = []
            continue
        if line.startswith('#'):
            continue
        cols = line.split('\t')
        if len(cols) >= 2 and cols[0].isdigit():
            tokens.append(cols[1])
    if tokens:
        sentences.append(' '.join(tokens))
    return '\n'.join(sentences), ''


def parse_document(path: Path) -> tuple[str, str, str]:
    ext = path.suffix.lower()
    if ext == '.txt':
        text, title = parse_txt(path)
        return text, title, 'txt'
    if ext == '.xml':
        text, title = parse_xml(path)
        return text, title, 'xml'
    if ext == '.json':
        text, title = parse_json(path)
        return text, title, 'json'
    if ext in {'.conllu', '.conll'}:
        text, title = parse_conllu(path)
        return text, title, 'conllu'
    raise ValueError(ext)


def meta_value(meta: dict, *names: str) -> str:
    for name in names:
        value = str(meta.get(name) or '').strip()
        if value:
            return value
    return ''


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
        ('source_format', pa.string()),
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
    rows: list[dict] = []
    count = 0
    chars = 0
    format_counts: dict[str, int] = {}
    skipped_empty = 0

    def flush() -> None:
        nonlocal writer, rows
        if not rows:
            return
        table = pa.Table.from_pylist(rows, schema=schema)
        if writer is None:
            writer = pq.ParquetWriter(out, schema, compression='zstd', compression_level=6, write_statistics=True)
        writer.write_table(table)
        rows = []

    paths = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED and '.git' not in p.parts)
    for path in paths:
        text, parsed_title, fmt = parse_document(path)
        if not text.strip():
            skipped_empty += 1
            continue
        rel = path.relative_to(root).as_posix()
        meta = catalog.get(rel) or catalog.get(path.name) or catalog.get(path.stem) or {}
        title = meta_value(meta, 'title', 'uniform_title', 'main_title', 'orig_title') or parsed_title or path.stem
        byline = meta_value(meta, 'byline', 'author', 'commentator', 'editor')
        era = meta_value(meta, 'era', 'date_ca', 'pub_year', 'date')
        category = meta_value(meta, 'group', 'orig_category', 'subcat_name', 'subcat', 'category', 'classification')
        doc_id = meta_value(meta, 'id', 'doc_id', 'catalog_no') or path.stem
        encoded = text.encode('utf-8')
        rows.append({
            'source_id': args.source_id,
            'source_repo': args.source_repo,
            'source_commit': args.source_commit,
            'license': args.license,
            'path': rel,
            'source_format': fmt,
            'doc_id': doc_id,
            'title': title,
            'byline': byline,
            'era': era,
            'category': category,
            'text': text,
            'text_chars': len(text),
            'text_sha256': sha256_bytes(encoded),
        })
        count += 1
        chars += len(text)
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        if len(rows) >= 128:
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
        'format_counts': format_counts,
        'skipped_empty': skipped_empty,
        'parquet_bytes': out.stat().st_size,
        'schema': schema.to_string(),
        'normalizer': 'osr-curated-multiformat-v2',
        'supported_extensions': sorted(SUPPORTED),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
