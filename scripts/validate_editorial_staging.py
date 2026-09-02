#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

REQUIRED_EDITORIAL = [
    'title_ko', 'core_summary_ko', 'what_happened_ko', 'background_cause_ko',
    'why_it_matters_ko', 'analysis_ko', 'future_impact_ko', 'next_checks_ko',
    'factcheck_status', 'factcheck_note_ko',
]
ALLOWED_FACTCHECK = {'CONFIRMED', 'PARTIALLY CONFIRMED', 'DISPUTED', 'UNVERIFIED'}
TARGET_CHAPTERS = {
    '국제 · 외교 · 안보', '과학', '경제 · 시장', '국내·해외 주식 · 이슈기업'
}


def has_hangul(value: str) -> bool:
    return bool(re.search(r'[가-힣]', value or ''))


def validate(data: dict, require_ready: bool, chapter: str | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    all_records = data.get('records', [])
    if data.get('schema_version') != 'priority-editorial-staging-v1':
        errors.append('unexpected staging schema')
    if len(all_records) != 40:
        errors.append(f'expected 40 staging records; found {len(all_records)}')
    chapters = Counter(r.get('chapter', '') for r in all_records)
    for ch in TARGET_CHAPTERS:
        if chapters.get(ch, 0) != 10:
            errors.append(f'{ch}: expected 10 staging records; found {chapters.get(ch, 0)}')

    if chapter:
        if chapter not in TARGET_CHAPTERS:
            errors.append(f'unsupported chapter scope: {chapter}')
        records = [r for r in all_records if r.get('chapter') == chapter]
        if len(records) != 10:
            errors.append(f'{chapter}: expected 10 scoped records; found {len(records)}')
    else:
        records = all_records

    seen_urls = set()
    verified = 0
    image_found = 0
    editorial_ready = 0
    for r in records:
        sid = r.get('staging_id', '<unknown>')
        src = r.get('source_record', {})
        ver = r.get('article_verification', {})
        img = r.get('image_provenance', {})
        ed = r.get('editorial', {})
        url = ver.get('canonical_url') or ver.get('final_url') or src.get('canonical_url') or src.get('url') or ''
        host = urlparse(url).netloc
        if not url.startswith(('http://', 'https://')) or not host:
            errors.append(f'{sid}: invalid final source URL')
        if url in seen_urls:
            errors.append(f'{sid}: duplicate final URL {url}')
        seen_urls.add(url)
        vstatus = ver.get('verification_status')
        if vstatus == 'VERIFIED':
            verified += 1
        else:
            warnings.append(f'{sid}: article verification {vstatus}')
        if img.get('image_status') == 'FOUND_UNREVIEWED':
            image_found += 1
        missing = [k for k in REQUIRED_EDITORIAL if not str(ed.get(k, '')).strip()]
        korean_fields = [k for k in REQUIRED_EDITORIAL if k.endswith('_ko')]
        non_korean = [k for k in korean_fields if str(ed.get(k, '')).strip() and not has_hangul(str(ed.get(k, '')))]
        fact = str(ed.get('factcheck_status', '')).strip()
        if fact and fact not in ALLOWED_FACTCHECK:
            errors.append(f'{sid}: invalid factcheck_status {fact}')
        if non_korean:
            errors.append(f'{sid}: Korean editorial fields without Hangul: {non_korean}')
        ready = not missing and not non_korean and fact in ALLOWED_FACTCHECK and vstatus == 'VERIFIED' and img.get('image_review_required') is False
        if ready:
            editorial_ready += 1
        elif require_ready:
            errors.append(f'{sid}: not publication-ready; missing={missing}, verification={vstatus}, image_review_required={img.get("image_review_required")}')

    if data.get('production_ready') is not False:
        errors.append('staging builder must never mark production_ready=true')
    scope = chapter or 'ALL'
    print(f"EDITORIAL_STAGING_AUDIT scope={scope} records={len(records)} verified={verified} images_found={image_found} editorial_ready={editorial_ready}")
    if require_ready and records and editorial_ready != len(records):
        errors.append(f'{scope}: ready count {editorial_ready} != scoped record count {len(records)}')
    if warnings:
        print('WARNINGS:')
        for w in warnings[:20]: print('  -', w)
        if len(warnings) > 20: print(f'  - ... {len(warnings)-20} more')
    return errors, warnings


def self_test() -> None:
    fake = {'schema_version':'priority-editorial-staging-v1','production_ready':False,'records':[]}
    errors, _ = validate(fake, False)
    assert any('expected 40' in e for e in errors)
    assert has_hangul('한국어 제목') and not has_hangul('English title')
    errors, _ = validate(fake, False, '국제 · 외교 · 안보')
    assert any('expected 10 scoped records' in e for e in errors)
    print('PASS: editorial staging validator self-test')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input')
    ap.add_argument('--require-ready', action='store_true')
    ap.add_argument('--chapter', choices=sorted(TARGET_CHAPTERS))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.input:
        ap.error('--input required')
    data = json.loads(Path(args.input).read_text(encoding='utf-8'))
    errors, _ = validate(data, args.require_ready, args.chapter)
    if errors:
        print('ERRORS:')
        for e in errors[:50]: print('  -', e)
        if len(errors) > 50: print(f'  - ... {len(errors)-50} more')
        return 2
    print('PASS: editorial staging audit')
    return 0

if __name__ == '__main__':
    sys.exit(main())
