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


def fingerprint(items: list[dict]) -> str:
    rows = [f"{x.get('chapter','')}|{record_url(x)}" for x in items]
    return hashlib.sha256('\n'.join(rows).encode('utf-8')).hexdigest()


def freeze(payload: dict, edition_date: str) -> tuple[dict, list[str]]:
    errors: list[str] = []
    selected = payload.get('selected') or []
    if payload.get('coverage_status') != 'PASS':
        errors.append('input arbitration coverage_status must be PASS')
    if len(selected) != 40:
        errors.append(f'expected exactly 40 selected records; found {len(selected)}')

    by_chapter: dict[str, list[dict]] = defaultdict(list)
    urls: list[str] = []
    for i, item in enumerate(selected, start=1):
        chapter = item.get('chapter', '')
        url = record_url(item)
        by_chapter[chapter].append(item)
        urls.append(url)
        if chapter not in CHAPTERS:
            errors.append(f'record {i}: unknown chapter {chapter!r}')
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            errors.append(f'record {i}: invalid canonical URL {url!r}')

    duplicates = [u for u, n in Counter(urls).items() if u and n > 1]
    if duplicates:
        errors.append(f'cross-chapter duplicate URLs: {duplicates[:10]}')
    for chapter in CHAPTERS:
        if len(by_chapter.get(chapter, [])) != 10:
            errors.append(f'{chapter}: expected 10 selected records; found {len(by_chapter.get(chapter, []))}')

    edition = f'daily-{edition_date}'
    input_edition = payload.get('edition')
    if input_edition and input_edition != edition:
        errors.append(f'input edition mismatch: expected {edition}, found {input_edition}')

    frozen = {
        'schema_version': 'priority-news-global-arbitration-frozen-v2',
        'edition': edition,
        'edition_date': edition_date,
        'source_schema_version': payload.get('schema_version'),
        'source_as_of': payload.get('as_of'),
        'selected_count': len(selected),
        'coverage_status': 'PASS' if not errors else 'FAIL',
        'chapter_report': payload.get('chapter_report') or {},
        'duplicate_groups_resolved': payload.get('duplicate_groups_resolved') or [],
        'backfilled': payload.get('backfilled') or [],
        'selection_fingerprint_sha256': fingerprint(selected),
        'selected': selected,
    }
    return frozen, errors


def self_test() -> None:
    rows = []
    for chapter in CHAPTERS:
        for i in range(10):
            rows.append({'chapter': chapter, 'url': f'https://example.com/{len(rows)}'})
    frozen, errors = freeze({'coverage_status': 'PASS', 'selected': rows}, '2099-01-02')
    assert not errors
    assert frozen['edition'] == 'daily-2099-01-02'
    assert frozen['selected_count'] == 40
    print('PASS: live priority freezer self-test')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='artifacts/priority-news-live-arbitrated.json')
    ap.add_argument('--output', default='artifacts/priority-news-frozen-arbitrated.json')
    ap.add_argument('--edition-date', required=False)
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.edition_date:
        print('FREEZE_LIVE_PRIORITY FAIL: --edition-date is required')
        return 2
    source = Path(args.input)
    if not source.is_absolute(): source = ROOT / source
    target = Path(args.output)
    if not target.is_absolute(): target = ROOT / target
    try:
        payload = load_json(source)
        frozen, errors = freeze(payload, args.edition_date)
    except Exception as exc:
        print(f'FREEZE_LIVE_PRIORITY FAIL load={type(exc).__name__}: {exc}')
        return 2
    if errors:
        print('FREEZE_LIVE_PRIORITY FAIL')
        for error in errors: print('  ERROR', error)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"FREEZE_LIVE_PRIORITY PASS edition={frozen['edition']} records={frozen['selected_count']} fingerprint={frozen['selection_fingerprint_sha256']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
