#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'config' / 'source-registry.json'
POLICY = ROOT / 'config' / 'source-policy.json'


def norm_domain(value: str) -> str:
    value = (value or '').strip().lower()
    if '://' in value:
        value = urlparse(value).hostname or ''
    if value.startswith('www.'):
        value = value[4:]
    return value.rstrip('.')


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    policy = json.loads(POLICY.read_text(encoding='utf-8'))

    sources = registry.get('sources')
    assert isinstance(sources, list) and sources, 'source-registry sources must be a non-empty list'

    ids = []
    domain_owner = {}
    tier_counts = Counter()
    access_counts = Counter()
    role_counts = Counter()
    topic_counts = Counter()

    required_keys = {'id', 'name', 'domains', 'tier', 'access', 'roles', 'topics'}
    for source in sources:
        missing = required_keys - set(source)
        assert not missing, f"{source.get('id','<unknown>')}: missing keys {sorted(missing)}"
        sid = source['id']
        ids.append(sid)
        assert isinstance(sid, str) and sid.strip(), 'source id must be non-empty string'
        assert source['tier'] in (0, 1, 2, 3, 4), f'{sid}: invalid tier'
        assert isinstance(source['domains'], list) and source['domains'], f'{sid}: domains required'
        assert isinstance(source['access'], list) and source['access'], f'{sid}: access required'
        assert isinstance(source['roles'], list) and source['roles'], f'{sid}: roles required'
        assert isinstance(source['topics'], list) and source['topics'], f'{sid}: topics required'
        for mode in source['access']:
            assert mode in {'api','rss','web'}, f'{sid}: unsupported access mode {mode}'
            access_counts[mode] += 1
        for role in source['roles']:
            role_counts[role] += 1
        for topic in source['topics']:
            topic_counts[topic] += 1
        tier_counts[source['tier']] += 1
        for raw in source['domains']:
            domain = norm_domain(raw)
            assert domain and '.' in domain, f'{sid}: invalid domain {raw!r}'
            previous = domain_owner.get(domain)
            if previous and previous != sid:
                raise AssertionError(f'domain {domain} assigned to both {previous} and {sid}')
            domain_owner[domain] = sid

    assert len(ids) == len(set(ids)), 'duplicate source ids found'
    assert tier_counts[0] >= 8, 'registry needs enough tier-0 structured/official sources'
    assert tier_counts[1] >= 20, 'registry needs enough tier-1 primary sources'
    assert tier_counts[2] >= 6, 'registry needs enough tier-2 news sources'
    assert tier_counts[3] >= 8, 'registry needs enough tier-3 specialist sources'
    assert tier_counts[4] >= 5, 'registry needs enough tier-4 discovery signals'
    assert access_counts['api'] >= 10, 'registry must include at least 10 API-capable sources'
    assert access_counts['rss'] >= 15, 'registry must include at least 15 RSS/feed-capable sources'

    critical_ids = {
        'pubmed','europe-pmc','crossref','clinicaltrials','sec','dart','krx','bok',
        'usgs','gdacs','noaa','korea-policy','openai','anthropic','cisa','aao','aoa',
        'arvo','reuters','ap','google-trends','youtube'
    }
    missing_critical = critical_ids - set(ids)
    assert not missing_critical, f'missing critical sources: {sorted(missing_critical)}'

    preferred = set()
    for chapter in policy.get('chapters', {}).values():
        preferred.update(norm_domain(d) for d in chapter.get('preferred_domains', []))
    discovery = {norm_domain(d) for d in policy.get('discovery_only_domains', [])}
    registered = set(domain_owner)
    covered = preferred & registered
    missing = sorted(preferred - registered)
    coverage = (len(covered) / len(preferred)) if preferred else 1.0

    print(f'PASS source-registry: {len(sources)} sources, {len(registered)} domains')
    print('tier counts:', dict(sorted(tier_counts.items())))
    print('access counts:', dict(access_counts))
    print(f'preferred-domain registry coverage: {len(covered)}/{len(preferred)} ({coverage:.1%})')
    if missing:
        print('INFO preferred domains not yet individually registered:', ', '.join(missing))
    discovery_unregistered = sorted(discovery - registered)
    if discovery_unregistered:
        print('INFO discovery-only domains not yet registered:', ', '.join(discovery_unregistered))

    # Phase-1 gate: registry structure and critical collectors are blocking;
    # preferred-domain completeness remains informational until the registry expands further.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
