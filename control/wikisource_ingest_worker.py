#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    print('+', ' '.join(cmd), flush=True)
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def rclone_cat(remote: str) -> str | None:
    p = run(['rclone', 'cat', remote], check=False, capture=True)
    if p.returncode != 0:
        return None
    return p.stdout.strip()


def rclone_copyto(local: Path, remote: str) -> None:
    run([
        'rclone', 'copyto', str(local), remote,
        '--drive-chunk-size', '64M',
        '--retries', '6',
        '--low-level-retries', '12',
        '--timeout', '10m',
        '--contimeout', '30s',
        '--stats', '30s',
    ])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def session() -> requests.Session:
    retry = Retry(
        total=7,
        connect=7,
        read=7,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET', 'HEAD']),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers['User-Agent'] = 'OSR-Wikisource-Ingest/1.0 (GitHub Actions; research corpus mirror)'
    s.mount('https://', HTTPAdapter(max_retries=retry))
    return s


def discover_latest_complete(s: requests.Session, wiki_id: str) -> tuple[str, str, str]:
    root = f'https://dumps.wikimedia.org/other/mediawiki_content_current/{wiki_id}/'
    r = s.get(root, timeout=60)
    r.raise_for_status()
    dates = sorted(set(re.findall(r'href=[\"\'](20\d{2}-\d{2}-\d{2})/', r.text)), reverse=True)
    if not dates:
        raise RuntimeError(f'No dated exports found for {wiki_id}')
    for date in dates:
        base = f'{root}{date}/xml/bzip2/'
        sums_url = urljoin(base, 'SHA256SUMS')
        sr = s.get(sums_url, timeout=60)
        if sr.status_code == 200 and sr.text.strip():
            return date, base, sr.text
    raise RuntimeError(f'No complete export with SHA256SUMS found for {wiki_id}')


def download_verified(s: requests.Session, url: str, dest: Path, expected_sha: str) -> tuple[int, float]:
    tmp = dest.with_suffix(dest.suffix + '.part')
    tmp.unlink(missing_ok=True)
    start = time.monotonic()
    h = hashlib.sha256()
    size = 0
    with s.get(url, stream=True, timeout=(30, 600)) as r:
        r.raise_for_status()
        with tmp.open('wb') as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
    got = h.hexdigest()
    if got.lower() != expected_sha.lower():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f'SHA256 mismatch for {url}: expected {expected_sha}, got {got}')
    os.replace(tmp, dest)
    return size, time.monotonic() - start


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--wiki-id', required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--request', default='control/wikisource_ingest_request.json')
    ap.add_argument('--work-dir', required=True)
    args = ap.parse_args()

    req = json.loads(Path(args.request).read_text(encoding='utf-8'))
    if req.get('action') != 'INGEST':
        raise RuntimeError('Request action is not INGEST')

    drive_remote = req.get('drive_remote', 'gdrive')
    destination_root = req['destination_root'].strip('/')
    build_parquet = bool(req.get('build_parquet', True))
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    ledger = work / f'{args.wiki_id}.ledger.jsonl'
    ledger.write_text('', encoding='utf-8')

    s = session()
    date, base_url, sums_text = discover_latest_complete(s, args.wiki_id)
    entries: list[tuple[str, str]] = []
    for raw in sums_text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(None, 1)
        if len(parts) != 2:
            continue
        expected_sha, filename = parts[0], parts[1].lstrip('*')
        if filename.endswith('.xml.bz2'):
            entries.append((expected_sha, filename))
    if not entries:
        raise RuntimeError(f'No XML.bz2 shards in SHA256SUMS for {args.wiki_id} {date}')

    remote_base = f'{drive_remote}:{destination_root}/{args.wiki_id}/{date}'
    sums_path = work / 'SHA256SUMS'
    sums_path.write_text(sums_text, encoding='utf-8')
    rclone_copyto(sums_path, f'{remote_base}/meta/SHA256SUMS')

    source_meta = {
        'schema_version': 'osr-wikisource-source-v1',
        'wiki_id': args.wiki_id,
        'label': args.label,
        'dataset': req.get('dataset', 'mediawiki_content_current'),
        'dump_date': date,
        'base_url': base_url,
        'sha256sums_url': urljoin(base_url, 'SHA256SUMS'),
        'shard_count': len(entries),
        'request_id': req['request_id'],
        'raw_policy': 'immutable',
        'normalized_policy': 'derived-parquet-with-provenance',
    }
    source_meta_path = work / 'SOURCE.json'
    write_text(source_meta_path, json.dumps(source_meta, ensure_ascii=False, indent=2) + '\n')
    rclone_copyto(source_meta_path, f'{remote_base}/meta/SOURCE.json')

    failures: list[dict] = []
    completed = 0
    skipped = 0
    total_downloaded = 0
    total_parquet = 0

    for idx, (expected_sha, filename) in enumerate(entries, start=1):
        source_url = urljoin(base_url, filename)
        parquet_name = filename[:-8] + '.parquet' if filename.endswith('.xml.bz2') else filename + '.parquet'
        raw_sha_remote = f'{remote_base}/raw/{filename}.sha256'
        parquet_sha_remote = f'{remote_base}/parquet/{parquet_name}.sha256'
        raw_done = rclone_cat(raw_sha_remote)
        parquet_done = rclone_cat(parquet_sha_remote) if build_parquet else expected_sha
        if raw_done and raw_done.split()[0] == expected_sha and parquet_done:
            print(f'[{idx}/{len(entries)}] SKIP complete {filename}', flush=True)
            skipped += 1
            with ledger.open('a', encoding='utf-8') as lf:
                lf.write(json.dumps({'wiki_id': args.wiki_id, 'dump_date': date, 'filename': filename, 'status': 'SKIPPED_ALREADY_COMPLETE', 'source_sha256': expected_sha}, ensure_ascii=False) + '\n')
            continue

        raw_path = work / filename
        parquet_path = work / parquet_name
        summary_path = work / f'{parquet_name}.summary.json'
        ingest_meta_path = work / f'{filename}.ingest.json'
        try:
            print(f'[{idx}/{len(entries)}] DOWNLOAD {source_url}', flush=True)
            size, seconds = download_verified(s, source_url, raw_path, expected_sha)
            total_downloaded += size

            rclone_copyto(raw_path, f'{remote_base}/raw/{filename}')
            raw_sidecar = work / f'{filename}.sha256'
            write_text(raw_sidecar, f'{expected_sha}  {filename}\n')
            rclone_copyto(raw_sidecar, raw_sha_remote)

            parquet_sha = None
            if build_parquet:
                run([
                    sys.executable, 'control/wikisource_dump_to_parquet.py',
                    '--input', str(raw_path),
                    '--output', str(parquet_path),
                    '--summary-json', str(summary_path),
                    '--wiki-id', args.wiki_id,
                    '--dump-date', date,
                    '--source-url', source_url,
                    '--source-sha256', expected_sha,
                ])
                parquet_sha = sha256_file(parquet_path)
                total_parquet += parquet_path.stat().st_size
                rclone_copyto(parquet_path, f'{remote_base}/parquet/{parquet_name}')
                parquet_sidecar = work / f'{parquet_name}.sha256'
                write_text(parquet_sidecar, f'{parquet_sha}  {parquet_name}\n')
                rclone_copyto(parquet_sidecar, parquet_sha_remote)
                rclone_copyto(summary_path, f'{remote_base}/meta/{parquet_name}.summary.json')

            ingest_meta = {
                'schema_version': 'osr-wikisource-ingest-record-v1',
                'request_id': req['request_id'],
                'wiki_id': args.wiki_id,
                'dump_date': date,
                'source_url': source_url,
                'source_filename': filename,
                'source_bytes': size,
                'source_sha256': expected_sha,
                'download_seconds': round(seconds, 3),
                'parquet_filename': parquet_name if build_parquet else None,
                'parquet_sha256': parquet_sha,
                'status': 'COMPLETE',
            }
            write_text(ingest_meta_path, json.dumps(ingest_meta, ensure_ascii=False, indent=2) + '\n')
            rclone_copyto(ingest_meta_path, f'{remote_base}/meta/{filename}.ingest.json')
            with ledger.open('a', encoding='utf-8') as lf:
                lf.write(json.dumps(ingest_meta, ensure_ascii=False) + '\n')
            completed += 1
        except Exception as exc:
            failure = {'wiki_id': args.wiki_id, 'dump_date': date, 'filename': filename, 'status': 'FAILED', 'error': repr(exc), 'source_sha256': expected_sha}
            failures.append(failure)
            with ledger.open('a', encoding='utf-8') as lf:
                lf.write(json.dumps(failure, ensure_ascii=False) + '\n')
            print(f'FAILED {filename}: {exc!r}', file=sys.stderr, flush=True)
        finally:
            for p in (raw_path, parquet_path, summary_path, ingest_meta_path):
                p.unlink(missing_ok=True)

    result = {
        'schema_version': 'osr-wikisource-worker-result-v1',
        'request_id': req['request_id'],
        'wiki_id': args.wiki_id,
        'label': args.label,
        'dump_date': date,
        'shards_expected': len(entries),
        'shards_completed_this_run': completed,
        'shards_skipped_complete': skipped,
        'shards_failed': len(failures),
        'downloaded_bytes_this_run': total_downloaded,
        'parquet_bytes_this_run': total_parquet,
        'status': 'PASS' if not failures else 'PARTIAL_FAILURE',
        'failures': failures,
    }
    result_path = work / f'{args.wiki_id}.result.json'
    write_text(result_path, json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    rclone_copyto(ledger, f'{remote_base}/meta/ledger-latest.jsonl')
    rclone_copyto(result_path, f'{remote_base}/meta/worker-result-latest.json')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == '__main__':
    raise SystemExit(main())
