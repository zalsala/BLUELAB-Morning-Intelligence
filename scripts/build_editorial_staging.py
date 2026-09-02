#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

UA = 'BLUELAB-Morning-Intelligence/1.0 (+https://github.com/zalsala/BLUELAB-Morning-Intelligence)'
TIMEOUT = 15
RETRYABLE = {429, 500, 502, 503, 504}

REQUIRED_EDITORIAL_FIELDS = [
    'title_ko', 'core_summary_ko', 'what_happened_ko', 'background_cause_ko',
    'why_it_matters_ko', 'analysis_ko', 'future_impact_ko', 'next_checks_ko',
    'factcheck_status', 'factcheck_note_ko',
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    value = html.unescape(value or '').lower()
    value = re.sub(r'[^a-z0-9가-힣]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def title_similarity(a: str, b: str) -> float:
    a, b = normalize_text(a), normalize_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ''
        self._in_title = False
        self.canonical = ''
        self.og_title = ''
        self.og_image = ''
        self.published = ''

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): (v or '') for k, v in attrs}
        t = tag.lower()
        if t == 'title':
            self._in_title = True
        elif t == 'link' and attrs.get('rel', '').lower() == 'canonical':
            self.canonical = attrs.get('href', '')
        elif t == 'meta':
            key = (attrs.get('property') or attrs.get('name') or '').lower()
            content = attrs.get('content', '')
            if key in {'og:title', 'twitter:title'} and not self.og_title:
                self.og_title = content
            elif key in {'og:image', 'twitter:image', 'twitter:image:src'} and not self.og_image:
                self.og_image = content
            elif key in {'article:published_time', 'datepublished', 'date', 'dc.date'} and not self.published:
                self.published = content
        elif t == 'time' and not self.published:
            self.published = attrs.get('datetime', '')

    def handle_endtag(self, tag):
        if tag.lower() == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def request_html(url: str, retries: int = 2) -> tuple[str, str, int]:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                ctype = (r.headers.get('Content-Type') or '').lower()
                if 'text/html' not in ctype and 'application/xhtml+xml' not in ctype:
                    raise RuntimeError(f'NON_HTML_CONTENT:{ctype}')
                raw = r.read(1_500_000)
                charset = r.headers.get_content_charset() or 'utf-8'
                return raw.decode(charset, errors='replace'), r.geturl(), int(getattr(r, 'status', 200))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRYABLE:
                break
        except Exception as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(1.0 * (2 ** attempt))
    raise last or RuntimeError('UNKNOWN_FETCH_ERROR')


def verify_article(item: dict) -> dict:
    requested = item.get('canonical_url') or item.get('url') or ''
    result = {
        'requested_url': requested,
        'final_url': '',
        'canonical_url': '',
        'http_status': None,
        'page_title': '',
        'title_similarity': 0.0,
        'published_at_page': '',
        'verification_status': 'UNVERIFIED',
        'verification_error': '',
    }
    image = {
        'image_url': '',
        'image_source_url': requested,
        'image_credit': '',
        'image_status': 'MISSING',
        'image_review_required': True,
    }
    if not requested.startswith(('http://', 'https://')):
        result['verification_status'] = 'INVALID_URL'
        return result, image
    try:
        text, final_url, status = request_html(requested)
        parser = MetaParser()
        parser.feed(text)
        page_title = (parser.og_title or parser.title or '').strip()
        canonical = urljoin(final_url, parser.canonical) if parser.canonical else final_url
        sim = title_similarity(item.get('title', ''), page_title)
        requested_domain = urlparse(requested).netloc.lower().removeprefix('www.')
        final_domain = urlparse(final_url).netloc.lower().removeprefix('www.')
        result.update({
            'final_url': final_url,
            'canonical_url': canonical,
            'http_status': status,
            'page_title': page_title,
            'title_similarity': round(sim, 3),
            'published_at_page': parser.published,
        })
        if requested_domain != final_domain:
            result['verification_status'] = 'REDIRECTED_DOMAIN_REVIEW'
        elif page_title and sim < 0.25:
            result['verification_status'] = 'TITLE_MISMATCH_REVIEW'
        else:
            result['verification_status'] = 'VERIFIED'
        if parser.og_image:
            image['image_url'] = urljoin(final_url, parser.og_image)
            image['image_source_url'] = final_url
            image['image_status'] = 'FOUND_UNREVIEWED'
    except urllib.error.HTTPError as exc:
        result['http_status'] = exc.code
        result['verification_status'] = f'HTTP_{exc.code}'
        result['verification_error'] = str(exc)
    except Exception as exc:
        name = type(exc).__name__.upper()
        result['verification_status'] = 'FETCH_ERROR'
        result['verification_error'] = f'{name}: {exc}'
    return result, image


def empty_editorial() -> dict:
    return {
        'title_ko': '',
        'core_summary_ko': '',
        'what_happened_ko': '',
        'background_cause_ko': '',
        'why_it_matters_ko': '',
        'analysis_ko': '',
        'future_impact_ko': '',
        'next_checks_ko': '',
        'factcheck_status': '',
        'factcheck_note_ko': '',
        'freshness_note_ko': '',
    }


def build(proposal: dict, live_verify: bool = True) -> dict:
    records = []
    for i, item in enumerate(proposal.get('replacement_candidates', []), start=1):
        verification, image = verify_article(item) if live_verify else (
            {'requested_url': item.get('canonical_url') or item.get('url', ''), 'verification_status': 'SKIPPED_OFFLINE'},
            {'image_url': '', 'image_source_url': item.get('canonical_url') or item.get('url', ''), 'image_credit': '', 'image_status': 'MISSING', 'image_review_required': True},
        )
        records.append({
            'staging_id': f'priority-{i:02d}',
            'chapter': item.get('chapter', ''),
            'source_record': {
                'source': item.get('source', ''),
                'collector_id': item.get('collector_id', ''),
                'tier': item.get('tier'),
                'title': item.get('title', ''),
                'summary': item.get('summary', ''),
                'published': item.get('published', ''),
                'url': item.get('url', ''),
                'canonical_url': item.get('canonical_url', ''),
                'selection_reason': item.get('selection_reason', ''),
            },
            'article_verification': verification,
            'image_provenance': image,
            'editorial': empty_editorial(),
            'editorial_status': 'PENDING_AUTHORING',
            'publication_eligible': False,
        })
    verified = sum(1 for r in records if r['article_verification'].get('verification_status') == 'VERIFIED')
    images = sum(1 for r in records if r['image_provenance'].get('image_status') == 'FOUND_UNREVIEWED')
    return {
        'schema_version': 'priority-editorial-staging-v1',
        'generated_at': now_iso(),
        'edition': proposal.get('edition'),
        'source_proposal_schema': proposal.get('schema_version'),
        'record_count': len(records),
        'article_verified_count': verified,
        'image_found_unreviewed_count': images,
        'editorial_ready_count': 0,
        'production_ready': False,
        'publication_status': 'STAGING_ONLY_DO_NOT_PUBLISH',
        'records': records,
    }


def self_test() -> None:
    assert title_similarity('G20 backs final statement', 'G20 backs final statement despite tensions') > 0.6
    e = empty_editorial()
    assert all(k in e for k in REQUIRED_EDITORIAL_FIELDS)
    fake = {'edition': 'test', 'schema_version': 'proposal-v1', 'replacement_candidates': [{'chapter': '국제 · 외교 · 안보', 'title': 'Test', 'url': 'https://example.com/a'}]}
    out = build(fake, live_verify=False)
    assert out['production_ready'] is False
    assert out['records'][0]['publication_eligible'] is False
    print('PASS: editorial staging builder self-test')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input')
    ap.add_argument('--output', default='artifacts/priority-editorial-staging.json')
    ap.add_argument('--no-live-verify', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.input:
        ap.error('--input required')
    proposal = json.loads(Path(args.input).read_text(encoding='utf-8'))
    out = build(proposal, live_verify=not args.no_live_verify)
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"EDITORIAL_STAGING records={out['record_count']} verified={out['article_verified_count']} images_unreviewed={out['image_found_unreviewed_count']} ready={out['editorial_ready_count']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
