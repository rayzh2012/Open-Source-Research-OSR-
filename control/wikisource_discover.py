#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def session() -> requests.Session:
    retry = Retry(
        total=6,
        connect=6,
        read=6,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET', 'HEAD']),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers['User-Agent'] = 'OSR-Wikisource-Discovery/1.0 (GitHub Actions research corpus manifest)'
    s.mount('https://', HTTPAdapter(max_retries=retry))
    return s


def latest_complete(s: requests.Session, wiki_id: str) -> tuple[str, str, str]:
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


def discover_wiki(s: requests.Session, wiki_id: str, label: str) -> dict:
    date, base, sums = latest_complete(s, wiki_id)
    shards = []
    for raw in sums.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(None, 1)
        if len(parts) != 2:
            continue
        sha, filename = parts[0].lower(), parts[1].lstrip('*')
        if not filename.endswith('.xml.bz2'):
            continue
        url = urljoin(base, filename)
        size = None
        try:
            hr = s.head(url, allow_redirects=True, timeout=60)
            if hr.ok and hr.headers.get('Content-Length'):
                size = int(hr.headers['Content-Length'])
        except Exception:
            pass
        shards.append({
            'index': len(shards),
            'filename': filename,
            'url': url,
            'sha256': sha,
            'bytes': size,
        })
    if not shards:
        raise RuntimeError(f'No XML.bz2 shards discovered for {wiki_id} {date}')
    known = sum(s['bytes'] or 0 for s in shards)
    return {
        'wiki_id': wiki_id,
        'label': label,
        'dump_date': date,
        'base_url': base,
        'sha256sums_url': urljoin(base, 'SHA256SUMS'),
        'shard_count': len(shards),
        'known_total_bytes': known,
        'all_sizes_known': all(s['bytes'] is not None for s in shards),
        'shards': shards,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets', default='control/wikisource_ingest_targets.json')
    ap.add_argument('--output', default='control/wikisource_discovery_manifest.json')
    args = ap.parse_args()
    targets = json.loads(Path(args.targets).read_text(encoding='utf-8'))
    enabled = [t for t in targets['targets'] if t.get('enabled')]
    s = session()
    wikis = [discover_wiki(s, t['wiki_id'], t['label']) for t in enabled]
    out = {
        'schema_version': 'osr-wikisource-discovery-v1',
        'dataset': 'mediawiki_content_current',
        'completion_gate': 'SHA256SUMS present',
        'wikis': wikis,
        'totals': {
            'wikis': len(wikis),
            'shards': sum(w['shard_count'] for w in wikis),
            'known_bytes': sum(w['known_total_bytes'] for w in wikis),
        },
    }
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out['totals'], ensure_ascii=False))
    for w in wikis:
        print(w['wiki_id'], w['dump_date'], w['shard_count'], w['known_total_bytes'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
