#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'editorial' / '2026-09-02' / 'priority-snapshot.json'
POLICY = ROOT / 'config' / 'source-policy.json'
CHAPTERS = (
    '국제 · 외교 · 안보',
    '과학',
    '경제 · 시장',
    '국내·해외 주식 · 이슈기업',
)


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix('www.')


def fingerprint(items: list[dict]) -> str:
    rows = sorted(f"{x.get('chapter','')}\t{x.get('canonical_url') or x.get('url','')}" for x in items)
    return hashlib.sha256('\n'.join(rows).encode('utf-8')).hexdigest()


def validate(data: dict, policy: dict) -> list[str]:
    errors: list[str] = []
    items = data.get('selected', [])
    target = int(data.get('target_per_chapter', 10))
    if data.get('schema_version') != 'priority-edition-snapshot-v1':
        errors.append('unexpected schema_version')
    if data.get('snapshot_status') != 'EDITORIALLY_AUDITED_NOT_PRODUCTION':
        errors.append('snapshot must remain non-production audited state')
    if len(items) != 40 or data.get('selected_count') != 40:
        errors.append(f"expected exactly 40 selected records; found {len(items)}")
    urls = [x.get('canonical_url') or x.get('url', '') for x in items]
    if any(not u.startswith(('http://', 'https://')) for u in urls):
        errors.append('all records require an absolute article URL')
    dup = [u for u, n in Counter(urls).items() if u and n > 1]
    if dup:
        errors.append(f'cross-snapshot duplicate URLs: {dup}')
    if data.get('cross_chapter_duplicate_urls'):
        errors.append('cross_chapter_duplicate_urls must be empty')

    expected_fp = data.get('selection_fingerprint_sha256', '')
    actual_fp = fingerprint(items)
    if actual_fp != expected_fp:
        errors.append(f'fingerprint mismatch expected={expected_fp} actual={actual_fp}')

    rejected_paths = set(policy.get('generic_url_paths_rejected_for_verified_articles', []))
    discovery = set(policy.get('discovery_only_domains', []))
    by_chapter: dict[str, list[dict]] = defaultdict(list)
    for x in items:
        by_chapter[x.get('chapter', '')].append(x)
    unknown = sorted(set(by_chapter) - set(CHAPTERS))
    if unknown:
        errors.append(f'unknown chapters: {unknown}')

    for chapter in CHAPTERS:
        rows = by_chapter.get(chapter, [])
        if len(rows) != target:
            errors.append(f'{chapter}: expected {target}, found {len(rows)}')
            continue
        counts = Counter(domain(x.get('canonical_url') or x.get('url', '')) for x in rows)
        counts.pop('', None)
        if len(counts) < 5:
            errors.append(f'{chapter}: unique domains {len(counts)} < 5')
        if counts and max(counts.values()) > 2:
            errors.append(f'{chapter}: domain cap exceeded {dict(counts)}')
        for x in rows:
            url = x.get('canonical_url') or x.get('url', '')
            d = domain(url)
            path = urlparse(url).path.rstrip('/') or '/'
            if d in discovery:
                errors.append(f'{chapter}: discovery-only final source {d}: {url}')
            if path in rejected_paths:
                errors.append(f'{chapter}: generic/section URL: {url}')
    return errors


def self_test() -> None:
    rows = []
    for c in CHAPTERS:
        for i in range(10):
            rows.append({'chapter': c, 'title': f't{i}', 'url': f'https://d{i%5}.example/a/{c}/{i}', 'canonical_url': f'https://d{i%5}.example/a/{c}/{i}'})
    data = {'schema_version':'priority-edition-snapshot-v1','snapshot_status':'EDITORIALLY_AUDITED_NOT_PRODUCTION','selected_count':40,'target_per_chapter':10,'cross_chapter_duplicate_urls':[],'selected':rows}
    data['selection_fingerprint_sha256'] = fingerprint(rows)
    assert validate(data, {'generic_url_paths_rejected_for_verified_articles':['/'],'discovery_only_domains':[]}) == []
    data['selected'][1]['canonical_url'] = data['selected'][0]['canonical_url']
    assert validate(data, {'generic_url_paths_rejected_for_verified_articles':['/'],'discovery_only_domains':[]})
    print('PASS: priority snapshot validator self-test')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=str(DEFAULT))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    data = json.loads(Path(args.input).read_text(encoding='utf-8'))
    policy = json.loads(POLICY.read_text(encoding='utf-8'))
    errors = validate(data, policy)
    print(f"PRIORITY_SNAPSHOT records={len(data.get('selected', []))} fingerprint={fingerprint(data.get('selected', []))} status={'PASS' if not errors else 'FAIL'}")
    for e in errors:
        print('  ERROR', e)
    return 0 if not errors else 2


if __name__ == '__main__':
    sys.exit(main())
