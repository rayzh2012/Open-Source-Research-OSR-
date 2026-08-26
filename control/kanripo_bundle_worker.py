#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

KR_RE = re.compile(r'\b(KR[0-9a-zA-Z]{6,8})\b')


def run(cmd: list[str], *, capture: bool = False, check: bool = True, cwd: str | None = None):
    return subprocess.run(cmd, text=True, capture_output=capture, check=check, cwd=cwd)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def stable_bucket(repo_id: str, partitions: int) -> int:
    return int(hashlib.sha256(repo_id.encode()).hexdigest()[:16], 16) % partitions


def extract_repo_ids(catalog_root: Path, globs: list[str]) -> list[str]:
    ids: set[str] = set()
    for pattern in globs:
        for p in glob.glob(str(catalog_root / pattern)):
            text = Path(p).read_text(encoding='utf-8', errors='replace')
            for rid in KR_RE.findall(text):
                ids.add(rid)
    return sorted(ids)


def ls_remote(repo_id: str) -> str | None:
    url = f'https://github.com/kanripo/{repo_id}.git'
    p = run(['git', 'ls-remote', url, 'HEAD'], capture=True, check=False)
    if p.returncode != 0 or not p.stdout.strip():
        return None
    return p.stdout.split()[0]


def download_commit(repo_id: str, commit: str, dest: Path) -> None:
    url = f'https://codeload.github.com/kanripo/{repo_id}/tar.gz/{commit}'
    tmp = dest.with_suffix('.tar.gz')
    run(['curl', '-fL', '--retry', '5', '--retry-delay', '2', '-o', str(tmp), url])
    with tarfile.open(tmp, 'r:gz') as tf:
        members = tf.getmembers()
        root_prefix = members[0].name.split('/', 1)[0] if members else ''
        tf.extractall(dest.parent / '_extract')
    extracted = dest.parent / '_extract' / root_prefix
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(extracted), str(dest))
    shutil.rmtree(dest.parent / '_extract', ignore_errors=True)
    tmp.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='control/kanripo_selected_config.json')
    ap.add_argument('--category', required=True)
    ap.add_argument('--partition', type=int, required=True)
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    cat = next(c for c in cfg['categories'] if c['id'] == args.category)
    partitions = int(cat['partitions'])
    if not 0 <= args.partition < partitions:
        raise SystemExit('partition out of range')

    work = Path(args.work_dir)
    out = Path(args.out_dir)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    catalog_root = work / 'KR-Catalog'
    if not catalog_root.exists():
        run(['git', 'clone', '--depth', '1', '--branch', cfg['catalog_ref'], f"https://github.com/{cfg['catalog_repo']}.git", str(catalog_root)])
    catalog_commit = run(['git', '-C', str(catalog_root), 'rev-parse', 'HEAD'], capture=True).stdout.strip()

    repo_ids = extract_repo_ids(catalog_root, cat['catalog_globs'])
    selected = [rid for rid in repo_ids if stable_bucket(rid, partitions) == args.partition]
    corpus_root = work / 'corpus'
    corpus_root.mkdir(exist_ok=True)

    records = []
    failures = []
    for i, rid in enumerate(selected, 1):
        print(f'[{i}/{len(selected)}] {rid}', flush=True)
        commit = ls_remote(rid)
        if not commit:
            failures.append({'repo_id': rid, 'error': 'HEAD_NOT_FOUND'})
            continue
        dest = corpus_root / rid
        try:
            download_commit(rid, commit, dest)
            text_files = list(dest.rglob('*.txt'))
            records.append({
                'repo_id': rid,
                'commit': commit,
                'text_files': len(text_files),
                'bytes': sum(p.stat().st_size for p in text_files),
            })
        except Exception as exc:
            failures.append({'repo_id': rid, 'commit': commit, 'error': repr(exc)})

    manifest = {
        'schema_version': 'osr-kanripo-selected-bundle-v1',
        'category': args.category,
        'label': cat['label'],
        'partition': args.partition,
        'partition_count': partitions,
        'catalog_repo': cfg['catalog_repo'],
        'catalog_commit': catalog_commit,
        'repos_catalog_total': len(repo_ids),
        'repos_selected': len(selected),
        'repos_completed': len(records),
        'repos_failed': len(failures),
        'repos': records,
        'failures': failures,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    snapshot_id = hashlib.sha256(manifest_bytes).hexdigest()
    manifest['snapshot_id'] = snapshot_id
    manifest_path = out / 'MANIFEST.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    bundle_path = out / f'{args.category}-part-{args.partition:02d}.tar.gz'
    with tarfile.open(bundle_path, 'w:gz', compresslevel=6) as tf:
        for rid in sorted(p.name for p in corpus_root.iterdir() if p.is_dir()):
            tf.add(corpus_root / rid, arcname=rid)
        tf.add(manifest_path, arcname='MANIFEST.json')

    result = {
        'category': args.category,
        'partition': args.partition,
        'snapshot_id': snapshot_id,
        'bundle': bundle_path.name,
        'bundle_bytes': bundle_path.stat().st_size,
        'bundle_sha256': sha256_file(bundle_path),
        'repos_completed': len(records),
        'repos_failed': len(failures),
        'corpus_root': str(corpus_root),
        'catalog_commit': catalog_commit,
    }
    (out / 'RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 3


if __name__ == '__main__':
    raise SystemExit(main())
