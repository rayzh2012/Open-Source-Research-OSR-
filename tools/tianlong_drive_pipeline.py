#!/usr/bin/env python3
"""Prepare complete three-edition Markdown snapshots for private Google Drive upload.

This script *never* writes copyrighted source text to the automation repository,
logs, commit history, or public GitHub Actions artifacts. For private research use.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

REPO = 'https://github.com/OliverCWY/JY'
EDITIONS = ('旧版', '三联版', '新修版')


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def get_commit(repo: Path) -> str:
    try:
        return subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return 'not-a-git-checkout'


def list_chapters(index: Path) -> list[dict[str, str]]:
    chapters = []
    for line in index.read_text(encoding='utf-8-sig').splitlines():
        match = re.search(r'^\s*-\s*\[([^]]+)\]\(([^)]+\.md)\)', line)
        if match:
            chapters.append({'title': match.group(1), 'filename': Path(unquote(match.group(2))).name})
    return chapters


def produce(source: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    content_root = output / 'Markdown'
    archive_root = output / 'ZIP'
    meta_root = output / 'INDEX'
    archive_root.mkdir(parents=True, exist_ok=True)
    meta_root.mkdir(parents=True, exist_ok=True)
    checksums: list[list[str | int]] = []
    volumes = {}
    for edition in EDITIONS:
        original = source / 'Markdown' / edition / '天龙八部'
        target = content_root / edition / '天龙八部'
        if not original.is_dir():
            raise FileNotFoundError(f'Missing edition: {original}')
        files = sorted(x for x in original.rglob('*.md') if x.is_file() and not x.is_symlink())
        if not files or not (original / 'index.md').is_file():
            raise ValueError(f'Edition missing index.md or Markdown chapters: {edition}')
        total_bytes = 0
        for file in files:
            relative = file.relative_to(original)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
            total_bytes += destination.stat().st_size
            checksums.append([edition, str(relative).replace('\\', '/'), destination.stat().st_size, sha256(destination)])
        volumes[edition] = {
            'markdown_files': len(files),
            'markdown_bytes': total_bytes,
            'chapter_index': list_chapters(original / 'index.md'),
        }
        archive = archive_root / f'天龙八部_{edition}_Markdown.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
            for file in sorted(target.rglob('*.md')):
                z.write(file, (Path(edition) / '天龙八部' / file.relative_to(target)).as_posix())
    with (meta_root / 'sha256.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['edition', 'relative_file', 'bytes', 'sha256'])
        writer.writerows(checksums)
    metadata = {
        'scope': '天龙八部：旧版／三联版／新修版 Markdown 全文（不包含其他金庸著作）',
        'source_repository': REPO,
        'source_commit': get_commit(source),
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'versions': volumes,
        'file_total': len(checksums),
        'file_bytes_total': sum(int(row[2]) for row in checksums),
        'notes': [
            'Third-party transcription, not verified original Ming Pao newspaper facsimile.',
            'Chapter counts exclude non-chapter index, afterword, and supplementary Markdown files.',
            'Downloaded texts remain in the authorized private Drive folder; not committed to this GitHub repository.',
        ],
    }
    (meta_root / 'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Checked-out OliverCWY/JY repository')
    parser.add_argument('--output', type=Path, required=True, help='Staging directory to upload to Drive')
    args = parser.parse_args()
    result = produce(args.source.resolve(), args.output.resolve())
    # Print metadata only; never print original copyrighted prose.
    print(json.dumps({k: result[k] for k in ('source_commit', 'file_total', 'file_bytes_total')}, ensure_ascii=False))
    print('Edition file counts:', {name: value['markdown_files'] for name, value in result['versions'].items()})


if __name__ == '__main__':
    main()