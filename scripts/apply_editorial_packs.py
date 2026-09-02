#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]


def norm_url(url: str) -> str:
    p = urlsplit((url or '').strip())
    host = p.netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    path = p.path.rstrip('/') or '/'
    return urlunsplit((p.scheme.lower() or 'https', host, path, '', ''))


def record_url(record: dict) -> str:
    ver = record.get('article_verification', {})
    src = record.get('source_record', {})
    return ver.get('canonical_url') or ver.get('final_url') or src.get('canonical_url') or src.get('url') or ''


def load_pack(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 'priority-editorial-pack-v1':
        raise ValueError(f'{path}: unexpected pack schema')
    return data


def apply(staging: dict, packs: list[dict]) -> tuple[dict, dict]:
    if staging.get('schema_version') != 'priority-editorial-staging-v1':
        raise ValueError('unexpected staging schema')
    index = {norm_url(record_url(r)): r for r in staging.get('records', [])}
    applied = []
    missing = []
    duplicate_pack_urls = []
    seen = set()

    for pack in packs:
        for item in pack.get('records', []):
            key = norm_url(item.get('canonical_url', ''))
            if not key:
                continue
            if key in seen:
                duplicate_pack_urls.append(key)
                continue
            seen.add(key)
            target = index.get(key)
            if not target:
                missing.append({'chapter': pack.get('chapter'), 'canonical_url': item.get('canonical_url')})
                continue
            if pack.get('chapter') and target.get('chapter') != pack.get('chapter'):
                missing.append({'chapter': pack.get('chapter'), 'canonical_url': item.get('canonical_url'), 'reason': 'chapter_mismatch'})
                continue
            target['editorial'] = dict(item.get('editorial', {}))
            target['editorial_status'] = 'AUTHORED_PACK_APPLIED'
            target['editorial_pack'] = {
                'schema_version': pack.get('schema_version'),
                'edition': pack.get('edition'),
                'chapter': pack.get('chapter'),
                'canonical_url': item.get('canonical_url'),
            }
            review = item.get('image_review', {})
            image = target.setdefault('image_provenance', {})
            decision = review.get('decision', '')
            if decision.startswith('APPROVED_') and image.get('image_url'):
                image['image_status'] = decision
                image['image_review_required'] = False
                image['image_credit'] = review.get('credit', '') or image.get('image_credit', '')
                image['image_review_note_ko'] = review.get('note_ko', '')
            elif decision == 'NO_IMAGE_ACCEPTED':
                image['image_status'] = decision
                image['image_review_required'] = False
                image['image_review_note_ko'] = review.get('note_ko', '')
            applied.append({'staging_id': target.get('staging_id'), 'chapter': target.get('chapter'), 'canonical_url': item.get('canonical_url')})

    staging['editorial_pack_application'] = {
        'applied_count': len(applied),
        'missing_count': len(missing),
        'duplicate_pack_url_count': len(duplicate_pack_urls),
        'applied': applied,
        'missing': missing,
        'duplicate_pack_urls': duplicate_pack_urls,
    }
    return staging, staging['editorial_pack_application']


def self_test() -> None:
    staging = {
        'schema_version': 'priority-editorial-staging-v1',
        'records': [{
            'staging_id':'p1','chapter':'국제 · 외교 · 안보',
            'source_record':{'canonical_url':'https://Example.com/a?x=1'},
            'article_verification':{'canonical_url':'https://example.com/a'},
            'image_provenance':{'image_url':'https://img.example/a.jpg','image_status':'FOUND_UNREVIEWED','image_review_required':True},
            'editorial':{},'editorial_status':'PENDING_AUTHORING'
        }]
    }
    pack = {'schema_version':'priority-editorial-pack-v1','edition':'x','chapter':'국제 · 외교 · 안보','records':[{
        'canonical_url':'https://www.example.com/a/',
        'editorial':{'title_ko':'테스트'},
        'image_review':{'decision':'APPROVED_EXACT_ARTICLE_OG','credit':'Example','note_ko':'원문 이미지'}
    }]}
    out, report = apply(staging, [pack])
    r = out['records'][0]
    assert report['applied_count'] == 1 and not report['missing']
    assert r['editorial']['title_ko'] == '테스트'
    assert r['image_provenance']['image_review_required'] is False
    assert r['image_provenance']['image_status'] == 'APPROVED_EXACT_ARTICLE_OG'
    print('PASS: editorial pack overlay self-test')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input')
    ap.add_argument('--pack', action='append', default=[])
    ap.add_argument('--output')
    ap.add_argument('--require-all-pack-records', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.input or not args.output or not args.pack:
        ap.error('--input, at least one --pack, and --output are required')
    staging = json.loads(Path(args.input).read_text(encoding='utf-8'))
    packs = [load_pack(Path(p)) for p in args.pack]
    out, report = apply(staging, packs)
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"EDITORIAL_PACKS applied={report['applied_count']} missing={report['missing_count']} duplicates={report['duplicate_pack_url_count']}")
    if report['missing']:
        for x in report['missing']: print('  MISSING', x)
    if report['duplicate_pack_urls']:
        for x in report['duplicate_pack_urls']: print('  DUPLICATE_PACK_URL', x)
    if args.require_all_pack_records and (report['missing'] or report['duplicate_pack_urls']):
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
