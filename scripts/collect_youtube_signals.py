#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config' / 'youtube-signals.json'
UA = 'BLUELAB-Morning-Intelligence/1.1 (+https://github.com/zalsala/BLUELAB-Morning-Intelligence)'
TIMEOUT = 20
ATOM = 'http://www.w3.org/2005/Atom'
YT = 'http://www.youtube.com/xml/schemas/2015'
RETRYABLE = {429, 500, 502, 503, 504}
API_BASE = 'https://www.googleapis.com/youtube/v3/playlistItems'


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def parse_dt(v):
    try:
        return dt.datetime.fromisoformat((v or '').replace('Z', '+00:00')).astimezone(dt.timezone.utc)
    except Exception:
        return None


def uploads_playlist_id(channel_id):
    return 'UU' + channel_id[2:] if channel_id.startswith('UC') else channel_id


def endpoints(channel_id):
    suffix = channel_id[2:] if channel_id.startswith('UC') else channel_id
    return [
        ('channel', f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'),
        ('uploads', f'https://www.youtube.com/feeds/videos.xml?playlist_id=UU{suffix}'),
        ('shorts', f'https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH{suffix}'),
    ]


def classify_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f'HTTP_{exc.code}'
    if isinstance(exc, socket.timeout) or isinstance(exc, TimeoutError):
        return 'TIMEOUT'
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, 'reason', None)
        if isinstance(reason, socket.timeout):
            return 'TIMEOUT'
        return 'NETWORK'
    if isinstance(exc, ET.ParseError):
        return 'XML_PARSE'
    if isinstance(exc, json.JSONDecodeError):
        return 'JSON_PARSE'
    return type(exc).__name__.upper()


def request_bytes(url, retries=3, accept='*/*'):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRYABLE:
                break
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(1.5 * (2 ** attempt))
    raise last


def request_json(url, retries=3):
    return json.loads(request_bytes(url, retries=retries, accept='application/json').decode('utf-8'))


def parse_feed(raw, cfg, limit=15, feed_kind='channel'):
    root = ET.fromstring(raw)
    out = []
    for e in root.findall(f'{{{ATOM}}}entry')[:limit]:
        vid = (e.findtext(f'{{{YT}}}videoId') or '').strip()
        title = (e.findtext(f'{{{ATOM}}}title') or '').strip()
        published = (e.findtext(f'{{{ATOM}}}published') or '').strip()
        updated = (e.findtext(f'{{{ATOM}}}updated') or '').strip()
        if not vid or not title:
            continue
        out.append({
            'channel_id': cfg['channel_id'], 'channel_name': cfg['name'], 'source_id': cfg['id'], 'tier': cfg['tier'],
            'video_id': vid, 'title': title, 'url': f'https://www.youtube.com/watch?v={vid}',
            'shorts_url': f'https://www.youtube.com/shorts/{vid}' if feed_kind == 'shorts' else '',
            'thumbnail_url': f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg', 'published_at': published, 'updated_at': updated,
            'source_domain': 'youtube.com', 'record_kind': 'youtube_short' if feed_kind == 'shorts' else 'youtube_video',
            'feed_kind': feed_kind, 'acquisition_method': 'rss',
        })
    return out


def fetch_channel_rss(cfg, limit):
    attempts = []
    for kind, url in endpoints(cfg['channel_id']):
        try:
            raw = request_bytes(url, accept='application/atom+xml, application/xml;q=0.9, */*;q=0.5')
            found = parse_feed(raw, cfg, limit, kind)
            if not found:
                attempts.append({'provider': 'rss', 'feed_kind': kind, 'url': url, 'status': 'ERROR', 'failure_class': 'EMPTY_FEED'})
                continue
            attempts.append({'provider': 'rss', 'feed_kind': kind, 'url': url, 'status': 'PASS', 'count': len(found)})
            return found, attempts, url, kind
        except Exception as exc:
            attempts.append({
                'provider': 'rss', 'feed_kind': kind, 'url': url, 'status': 'ERROR',
                'failure_class': classify_error(exc), 'error': f'{type(exc).__name__}: {exc}',
            })
    return [], attempts, '', ''


def fetch_channel_api(cfg, limit, api_key):
    if not api_key:
        return [], [{'provider': 'youtube_data_api', 'status': 'SKIPPED', 'failure_class': 'MISSING_API_KEY'}], '', 'uploads'
    params = urllib.parse.urlencode({
        'part': 'snippet,contentDetails',
        'playlistId': uploads_playlist_id(cfg['channel_id']),
        'maxResults': min(50, max(1, limit)),
        'key': api_key,
    })
    url = f'{API_BASE}?{params}'
    attempts = []
    try:
        data = request_json(url)
        items = data.get('items') or []
        found = []
        for item in items[:limit]:
            snippet = item.get('snippet') or {}
            details = item.get('contentDetails') or {}
            resource = snippet.get('resourceId') or {}
            vid = (details.get('videoId') or resource.get('videoId') or '').strip()
            title = (snippet.get('title') or '').strip()
            published = (details.get('videoPublishedAt') or snippet.get('publishedAt') or '').strip()
            if not vid or not title or title in {'Private video', 'Deleted video'}:
                continue
            thumbs = snippet.get('thumbnails') or {}
            thumb = ((thumbs.get('high') or thumbs.get('medium') or thumbs.get('default') or {}).get('url') or f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg')
            found.append({
                'channel_id': cfg['channel_id'], 'channel_name': cfg['name'], 'source_id': cfg['id'], 'tier': cfg['tier'],
                'video_id': vid, 'title': title, 'url': f'https://www.youtube.com/watch?v={vid}', 'shorts_url': '',
                'thumbnail_url': thumb, 'published_at': published, 'updated_at': published,
                'source_domain': 'youtube.com', 'record_kind': 'youtube_video', 'feed_kind': 'uploads',
                'acquisition_method': 'youtube_data_api',
            })
        if not found:
            attempts.append({'provider': 'youtube_data_api', 'status': 'ERROR', 'failure_class': 'EMPTY_API_RESULT'})
            return [], attempts, url, 'uploads'
        attempts.append({'provider': 'youtube_data_api', 'status': 'PASS', 'count': len(found)})
        return found, attempts, url, 'uploads'
    except Exception as exc:
        attempts.append({
            'provider': 'youtube_data_api', 'status': 'ERROR', 'failure_class': classify_error(exc),
            'error': f'{type(exc).__name__}: {exc}',
        })
        return [], attempts, url, 'uploads'


def fetch_channel(cfg, limit, api_key):
    api_found, api_attempts, api_url, api_kind = fetch_channel_api(cfg, limit, api_key)
    if api_found:
        return api_found, api_attempts, api_url, api_kind, 'youtube_data_api'
    rss_found, rss_attempts, rss_url, rss_kind = fetch_channel_rss(cfg, limit)
    attempts = api_attempts + rss_attempts
    if rss_found:
        return rss_found, attempts, rss_url, rss_kind, 'rss_fallback'
    return [], attempts, '', '', 'unavailable'


def collect(limit_per_channel=15, api_key=None):
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    api_key = api_key if api_key is not None else os.getenv('YOUTUBE_API_KEY', '').strip()
    records, errors, status = [], [], []
    for ch in cfg['channels']:
        found, attempts, source_url, source_kind, method = fetch_channel(ch, limit_per_channel, api_key)
        records.extend(found)
        if found:
            status.append({
                'source_id': ch['id'], 'status': 'PASS', 'count': len(found), 'source_url': source_url,
                'source_kind': source_kind, 'acquisition_method': method, 'attempts': attempts,
            })
        else:
            classes = [a.get('failure_class') for a in attempts if a.get('failure_class')]
            errors.append({'source_id': ch['id'], 'error': 'all YouTube acquisition methods failed', 'failure_classes': classes, 'attempts': attempts})
            status.append({'source_id': ch['id'], 'status': 'ERROR', 'count': 0, 'acquisition_method': method, 'failure_classes': classes, 'attempts': attempts})

    seen, dedup = set(), []
    for r in records:
        if r['video_id'] in seen:
            continue
        seen.add(r['video_id'])
        dedup.append(r)

    healthy = sum(1 for x in status if x['status'] == 'PASS')
    api_successes = sum(1 for x in status if x.get('acquisition_method') == 'youtube_data_api')
    rss_fallback_successes = sum(1 for x in status if x.get('acquisition_method') == 'rss_fallback')
    if healthy == len(status) and api_successes == healthy:
        health = 'HEALTHY'
    elif healthy:
        health = 'DEGRADED'
    else:
        health = 'UNAVAILABLE'
    provider_state = 'API_ACTIVE' if api_key else 'MISSING_API_KEY'
    return {
        'schema_version': 'youtube-signals-candidates-v4', 'generated_at': now().isoformat(),
        'provider_state': provider_state, 'candidate_count': len(dedup), 'error_count': len(errors),
        'healthy_source_count': healthy, 'api_success_count': api_successes, 'rss_fallback_success_count': rss_fallback_successes,
        'source_health': health, 'source_status': status, 'errors': errors, 'candidates': dedup,
    }


def select(data):
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    asof = parse_dt(data.get('generated_at')) or now()
    ranked, rejected = [], Counter()
    for c in data.get('candidates', []):
        d = parse_dt(c.get('published_at'))
        if not d:
            rejected['missing_date'] += 1
            continue
        age = (asof - d).total_seconds() / 86400
        if age < -1:
            rejected['future_date'] += 1
            continue
        if age > cfg['max_age_days']:
            rejected['stale'] += 1
            continue
        freshness = max(0, cfg['max_age_days'] - max(0, age))
        trust = max(0, 4 - int(c.get('tier', 4)))
        ranked.append((freshness * 10 + trust, d, c))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    chosen, per = [], Counter()
    for score, d, c in ranked:
        sid = c['source_id']
        if per[sid] >= cfg['max_per_channel']:
            continue
        item = dict(c)
        item['selection_score'] = round(score, 2)
        chosen.append(item)
        per[sid] += 1
        if len(chosen) >= cfg['target']:
            break
    status = 'PASS' if len(chosen) >= cfg['target'] and len(per) >= cfg['minimum_unique_channels'] else 'FAIL'
    return {
        'schema_version': 'youtube-signals-selection-v4', 'generated_at': now().isoformat(), 'as_of': asof.isoformat(),
        'coverage_status': status, 'provider_state': data.get('provider_state', 'UNKNOWN'),
        'source_health': data.get('source_health', 'UNKNOWN'), 'source_error_count': data.get('error_count', 0),
        'selected_count': len(chosen), 'unique_channels': len(per), 'channel_counts': dict(per),
        'reject_counts': dict(rejected), 'selected': chosen,
    }


def self_test():
    raw = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>abc123</yt:videoId><title>Example video</title><published>2026-09-02T00:00:00+00:00</published><updated>2026-09-02T00:01:00+00:00</updated></entry></feed>'''
    cfg = {'channel_id': 'UCX', 'name': 'Example', 'id': 'example', 'tier': 2}
    got = parse_feed(raw, cfg, feed_kind='shorts')
    assert got[0]['url'] == 'https://www.youtube.com/watch?v=abc123'
    assert got[0]['shorts_url'].endswith('/abc123')
    assert uploads_playlist_id('UCABC') == 'UUABC'
    eps = endpoints('UCABC')
    assert 'playlist_id=UUABC' in eps[1][1] and 'playlist_id=UUSHABC' in eps[2][1]
    assert classify_error(urllib.error.HTTPError('https://x', 429, 'rate', {}, None)) == 'HTTP_429'
    conf = json.loads(CONFIG.read_text(encoding='utf-8'))
    assert len(conf['channels']) >= 4
    print('PASS: youtube signals collector self-test')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--limit-per-channel', type=int, default=15)
    ap.add_argument('--output', default='artifacts/youtube-signals-live.json')
    ap.add_argument('--selected-output', default='artifacts/youtube-signals-selected.json')
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return 0
    data = collect(a.limit_per_channel)
    sel = select(data)
    p = Path(a.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    s = Path(a.selected_output)
    s.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding='utf-8')
    print(
        f"YOUTUBE provider={data['provider_state']} candidates={data['candidate_count']} errors={data['error_count']} "
        f"health={data['source_health']} api={data['api_success_count']} rss_fallback={data['rss_fallback_success_count']} "
        f"selected={sel['selected_count']} channels={sel['unique_channels']} coverage={sel['coverage_status']}"
    )
    for x in data['source_status']:
        print(' ', {k: v for k, v in x.items() if k != 'attempts'})
    return 0 if sel['coverage_status'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
