#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    print('+', ' '.join(cmd[:6]) + (' ...' if len(cmd) > 6 else ''), flush=True)
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def session() -> requests.Session:
    retry = Retry(total=7, connect=7, read=7, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(['GET', 'HEAD']), raise_on_status=False)
    s = requests.Session()
    s.headers['User-Agent'] = 'OSR-Wikisource-Shard-Ingest/1.0 (GitHub Actions research corpus mirror)'
    s.mount('https://', HTTPAdapter(max_retries=retry))
    return s


def rclone_cat(remote: str) -> str | None:
    p = run(['rclone', 'cat', remote], check=False, capture=True)
    return p.stdout.strip() if p.returncode == 0 else None


def rclone_copyto(local: Path, remote: str) -> None:
    run([
        'rclone', 'copyto', str(local), remote,
        '--drive-chunk-size', '64M',
        '--retries', '6', '--low-level-retries', '12',
        '--timeout', '10m', '--contimeout', '30s', '--stats', '30s',
    ])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download_verified(s: requests.Session, url: str, dest: Path, expected_sha: str) -> tuple[int, float]:
    tmp = dest.with_suffix(dest.suffix + '.part')
    tmp.unlink(missing_ok=True)
    h = hashlib.sha256(); size = 0; start = time.monotonic()
    with s.get(url, stream=True, timeout=(30, 900)) as r:
        r.raise_for_status()
        with tmp.open('wb') as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk); h.update(chunk); size += len(chunk)
    got = h.hexdigest()
    if got.lower() != expected_sha.lower():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f'SHA256 mismatch expected={expected_sha} got={got}')
    os.replace(tmp, dest)
    return size, time.monotonic() - start


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--request', required=True)
    ap.add_argument('--wiki-id', required=True)
    ap.add_argument('--shard-index', type=int, required=True)
    ap.add_argument('--work-dir', required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    request = json.loads(Path(args.request).read_text(encoding='utf-8'))
    wiki = next(w for w in manifest['wikis'] if w['wiki_id'] == args.wiki_id)
    shard = next(s for s in wiki['shards'] if int(s['index']) == args.shard_index)

    work = Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)
    filename = shard['filename']; source_url = shard['url']; expected_sha = shard['sha256']
    dump_date = wiki['dump_date']; label = wiki['label']
    parquet_name = filename[:-8] + '.parquet'
    raw_path = work / filename
    parquet_path = work / parquet_name
    summary_path = work / f'{parquet_name}.summary.json'
    result_path = work / 'result.json'

    drive_remote = request.get('drive_remote', 'gdrive')
    destination_root = request['destination_root'].strip('/')
    remote_base = f'{drive_remote}:{destination_root}/{args.wiki_id}/{dump_date}'
    raw_sha_remote = f'{remote_base}/raw/{filename}.sha256'
    parquet_sha_remote = f'{remote_base}/parquet/{parquet_name}.sha256'

    existing_raw = rclone_cat(raw_sha_remote)
    existing_parquet = rclone_cat(parquet_sha_remote)
    if existing_raw and existing_raw.split()[0] == expected_sha and existing_parquet:
        result = {
            'schema_version': 'osr-wikisource-shard-result-v1',
            'request_id': request['request_id'], 'wiki_id': args.wiki_id, 'label': label,
            'dump_date': dump_date, 'shard_index': args.shard_index, 'filename': filename,
            'source_sha256': expected_sha, 'status': 'SKIPPED_ALREADY_COMPLETE'
        }
        write_json(result_path, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    s = session()
    try:
        size, seconds = download_verified(s, source_url, raw_path, expected_sha)
        if shard.get('bytes') is not None and int(shard['bytes']) != size:
            raise RuntimeError(f'Content-Length mismatch manifest={shard["bytes"]} downloaded={size}')

        rclone_copyto(raw_path, f'{remote_base}/raw/{filename}')
        raw_sidecar = work / f'{filename}.sha256'
        raw_sidecar.write_text(f'{expected_sha}  {filename}\n', encoding='utf-8')
        rclone_copyto(raw_sidecar, raw_sha_remote)

        run([
            sys.executable, 'control/wikisource_dump_to_parquet.py',
            '--input', str(raw_path), '--output', str(parquet_path),
            '--summary-json', str(summary_path), '--wiki-id', args.wiki_id,
            '--dump-date', dump_date, '--source-url', source_url,
            '--source-sha256', expected_sha,
        ])
        parquet_sha = sha256_file(parquet_path)
        parquet_sidecar = work / f'{parquet_name}.sha256'
        parquet_sidecar.write_text(f'{parquet_sha}  {parquet_name}\n', encoding='utf-8')
        rclone_copyto(parquet_path, f'{remote_base}/parquet/{parquet_name}')
        rclone_copyto(parquet_sidecar, parquet_sha_remote)
        rclone_copyto(summary_path, f'{remote_base}/meta/{parquet_name}.summary.json')

        result = {
            'schema_version': 'osr-wikisource-shard-result-v1',
            'request_id': request['request_id'], 'wiki_id': args.wiki_id, 'label': label,
            'dump_date': dump_date, 'shard_index': args.shard_index, 'filename': filename,
            'source_url': source_url, 'source_bytes': size, 'source_sha256': expected_sha,
            'download_seconds': round(seconds, 3), 'parquet_filename': parquet_name,
            'parquet_bytes': parquet_path.stat().st_size, 'parquet_sha256': parquet_sha,
            'status': 'PASS'
        }
        write_json(result_path, result)
        rclone_copyto(result_path, f'{remote_base}/meta/{filename}.ingest.json')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = {
            'schema_version': 'osr-wikisource-shard-result-v1',
            'request_id': request['request_id'], 'wiki_id': args.wiki_id,
            'dump_date': dump_date, 'shard_index': args.shard_index, 'filename': filename,
            'source_sha256': expected_sha, 'status': 'FAILED', 'error': repr(exc)
        }
        write_json(result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    finally:
        for p in (raw_path, parquet_path):
            p.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
