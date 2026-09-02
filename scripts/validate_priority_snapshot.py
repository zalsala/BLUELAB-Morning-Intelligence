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


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def record_url(item: dict) -> str:
    return (item.get('canonical_url') or item.get('url') or '').strip()


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix('www.')


def fingerprint(items: list[dict]) -> str:
    rows = [f"{x.get('chapter','')}|{record_url(x)}" for x in items]
    return hashlib.sha256('\n'.join(rows).encode('utf-8')).hexdigest()


def load_snapshot(manifest_path: Path) -> tuple[dict, list[dict]]:
    manifest = load_json(manifest_path)
    selected: list[dict] = []
    for rel in manifest.get('selected_files') or []:
        chunk = load_json(ROOT / rel)
        rows = chunk.get('selected') or []
        if chunk.get('schema_version') != 'priority-edition-snapshot-chapter-v1':
            raise ValueError(f'{rel}: unsupported chapter snapshot schema')
        if chunk.get('edition') != manifest.get('edition'):
            raise ValueError(f'{rel}: edition mismatch')
        if chunk.get('selected_count') != len(rows):
            raise ValueError(f'{rel}: selected_count mismatch')
        if any(x.get('chapter') != chunk.get('chapter') for x in rows):
            raise ValueError(f'{rel}: row chapter mismatch')
        selected.extend(rows)
    return manifest, selected


def validate(manifest: dict, items: list[dict], policy: dict) -> list[str]:
    errors: list[str] = []
    if manifest.get('schema_version') != 'priority-edition-snapshot-v2':
        errors.append('unexpected schema_version')
    if manifest.get('snapshot_status') != 'EDITORIALLY_AUDITED_NOT_PRODUCTION':
        errors.append('snapshot must remain non-production audited state')
    files = manifest.get('selected_files') or []
    if len(files) != 4 or len(set(files)) != 4:
        errors.append(f'exactly four unique selected_files required; found {len(files)}')
    if len(items) != 40 or manifest.get('selected_count') != 40:
        errors.append(f"expected exactly 40 selected records; found {len(items)}")
    if manifest.get('target_per_chapter') != 10:
        errors.append('target_per_chapter must be 10')
    if manifest.get('cross_chapter_duplicate_urls'):
        errors.append('cross_chapter_duplicate_urls must be empty')

    urls = [record_url(x) for x in items]
    if any(urlparse(u).scheme not in ('http', 'https') or not urlparse(u).netloc for u in urls):
        errors.append('all records require an absolute article URL')
    dup = [u for u, n in Counter(urls).items() if u and n > 1]
    if dup:
        errors.append(f'cross-snapshot duplicate URLs: {dup}')

    expected_fp = manifest.get('selection_fingerprint_sha256', '')
    actual_fp = fingerprint(items)
    if manifest.get('fingerprint_algorithm') != 'sha256(ordered newline-joined chapter|canonical_url)':
        errors.append('unexpected fingerprint_algorithm')
    if actual_fp != expected_fp:
        errors.append(f'fingerprint mismatch expected={expected_fp} actual={actual_fp}')

    rejected_paths = set(policy.get('generic_url_paths_rejected_for_verified_articles', []))
    discovery = set(policy.get('discovery_only_domains', []))
    by_chapter: dict[str, list[dict]] = defaultdict(list)
    for i, x in enumerate(items, start=1):
        for field in ('chapter', 'source', 'title', 'published', 'domain'):
            if x.get(field) in (None, ''):
                errors.append(f'record {i}: missing {field}')
        by_chapter[x.get('chapter', '')].append(x)
    unknown = sorted(set(by_chapter) - set(CHAPTERS))
    if unknown:
        errors.append(f'unknown chapters: {unknown}')

    target = int(manifest.get('target_per_chapter', 10))
    min_domains = int(manifest.get('minimum_unique_domains', 5))
    max_per_domain = int(manifest.get('max_per_domain', 2))
    reports = manifest.get('chapter_report') or {}
    for chapter in CHAPTERS:
        rows = by_chapter.get(chapter, [])
        if len(rows) != target:
            errors.append(f'{chapter}: expected {target}, found {len(rows)}')
            continue
        counts = Counter(x.get('domain') for x in rows if x.get('domain'))
        if len(counts) < min_domains:
            errors.append(f'{chapter}: unique domains {len(counts)} < {min_domains}')
        if counts and max(counts.values()) > max_per_domain:
            errors.append(f'{chapter}: domain cap exceeded {dict(counts)}')
        report = reports.get(chapter) or {}
        if report.get('selected_count') != len(rows):
            errors.append(f'{chapter}: chapter_report selected_count mismatch')
        if report.get('unique_domains') != len(counts):
            errors.append(f'{chapter}: chapter_report unique_domains mismatch')
        if report.get('domain_counts') != dict(counts):
            errors.append(f'{chapter}: chapter_report domain_counts mismatch')
        if report.get('status') != 'PASS':
            errors.append(f'{chapter}: chapter_report status must be PASS')
        for x in rows:
            url = record_url(x)
            d = domain(url)
            path = urlparse(url).path.rstrip('/') or '/'
            if d in discovery:
                errors.append(f'{chapter}: discovery-only final source {d}: {url}')
            if path in rejected_paths:
                errors.append(f'{chapter}: generic/section URL: {url}')
    return errors


def self_test() -> None:
    rows = [
        {'chapter': 'A', 'canonical_url': 'https://example.com/a'},
        {'chapter': 'B', 'canonical_url': 'https://example.com/b'},
    ]
    expected = hashlib.sha256('A|https://example.com/a\nB|https://example.com/b'.encode()).hexdigest()
    assert fingerprint(rows) == expected
    print('PASS: priority snapshot validator self-test')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=str(DEFAULT))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    path = Path(args.input)
    if not path.is_absolute():
        path = ROOT / path
    policy = load_json(POLICY)
    try:
        manifest, items = load_snapshot(path)
        errors = validate(manifest, items, policy)
    except Exception as exc:
        print(f'PRIORITY_SNAPSHOT FAIL load={type(exc).__name__}: {exc}')
        return 2
    print(f"PRIORITY_SNAPSHOT records={len(items)} fingerprint={fingerprint(items)} status={'PASS' if not errors else 'FAIL'}")
    for e in errors:
        print('  ERROR', e)
    return 0 if not errors else 2


if __name__ == '__main__':
    sys.exit(main())
