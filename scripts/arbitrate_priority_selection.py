#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import select_priority_news as base

TARGET=10


def canonical_key(url):
    try:
        p=urlsplit(url or '')
        host=p.netloc.lower().removeprefix('www.')
        return urlunsplit((p.scheme.lower(),host,p.path.rstrip('/'),'',''))
    except Exception:
        return (url or '').strip()


def preferred_chapter(items):
    chapters={x['chapter'] for x in items}
    title=' '.join(x.get('title','') for x in items)
    if '국내·해외 주식 · 이슈기업' in chapters and base.count_terms(title, base.STOCK_STRONG_TITLE_TERMS):
        return '국내·해외 주식 · 이슈기업'
    if '국제 · 외교 · 안보' in chapters and '경제 · 시장' in chapters:
        if base.count_terms(title, base.ECONOMY_STRONG_TITLE_TERMS) < 1:
            return '국제 · 외교 · 안보'
    return items[0]['chapter']


def rank_candidates(candidates, chapter, asof):
    ranked=[]
    for c in candidates:
        if c.get('chapter') != chapter:
            continue
        score,reason=base.score(c,asof)
        if reason:
            continue
        ranked.append((score,base.parse_dt(c.get('published')),c))
    ranked.sort(key=lambda z:(z[0],z[1]),reverse=True)
    return ranked


def valid_add(chosen, candidate, globally_used):
    key=canonical_key(candidate.get('canonical_url') or candidate.get('url'))
    if not key or key in globally_used:
        return False
    domain=candidate.get('domain') or urlsplit(candidate.get('url','')).netloc.lower().removeprefix('www.')
    if Counter(x.get('domain') or urlsplit(x.get('url','')).netloc.lower().removeprefix('www.') for x in chosen)[domain] >= base.MAX_PER_DOMAIN:
        return False
    if any(base.same_event(candidate.get('title'),x.get('title')) for x in chosen):
        return False
    return True


def arbitrate(candidate_data, selected_data, target=TARGET):
    asof=base.resolve_asof(candidate_data, selected_data.get('as_of'))
    selected=[dict(x) for x in selected_data.get('selected',[])]
    by_url=defaultdict(list)
    for item in selected:
        by_url[canonical_key(item.get('canonical_url') or item.get('url'))].append(item)

    removed=[]
    kept=[]
    duplicate_groups=[]
    for key,items in by_url.items():
        chapters={x['chapter'] for x in items}
        if len(items)>1 and len(chapters)>1:
            winner=preferred_chapter(items)
            duplicate_groups.append({'url':key,'chapters':sorted(chapters),'winner':winner,'titles':sorted({x.get('title','') for x in items})})
            winner_kept=False
            for item in items:
                if item['chapter']==winner and not winner_kept:
                    kept.append(item); winner_kept=True
                else:
                    removed.append(item)
        else:
            kept.extend(items)

    by_chapter=defaultdict(list)
    for item in kept:
        by_chapter[item['chapter']].append(item)
    globally_used={canonical_key(x.get('canonical_url') or x.get('url')) for x in kept}
    backfilled=[]

    for chapter in base.POLICY:
        chosen=by_chapter[chapter]
        if len(chosen)>=target:
            continue
        for score,published,c in rank_candidates(candidate_data.get('candidates',[]),chapter,asof):
            if not valid_add(chosen,c,globally_used):
                continue
            item=dict(c)
            item['selection_score']=round(score,2)
            item['selection_reason']='global_arbitration_backfill'
            chosen.append(item)
            globally_used.add(canonical_key(item.get('canonical_url') or item.get('url')))
            backfilled.append({'chapter':chapter,'title':item.get('title'),'url':item.get('url')})
            if len(chosen)>=target:
                break

    final=[]; report={}
    for chapter in base.POLICY:
        chosen=by_chapter[chapter]
        domains=Counter(x.get('domain') or urlsplit(x.get('url','')).netloc.lower().removeprefix('www.') for x in chosen)
        status='PASS' if len(chosen)>=target and len(domains)>=base.MIN_DOMAINS else 'FAIL'
        report[chapter]={'selected_count':len(chosen),'unique_domains':len(domains),'domain_counts':dict(domains),'status':status}
        final.extend(chosen)

    keys=[canonical_key(x.get('canonical_url') or x.get('url')) for x in final]
    cross_duplicates=[k for k,n in Counter(keys).items() if k and n>1]
    status='PASS' if all(x['status']=='PASS' for x in report.values()) and not cross_duplicates else 'FAIL'
    return {
      'schema_version':'priority-news-global-arbitration-v1','generated_at':base.datetime.now(base.timezone.utc).isoformat(),
      'as_of':asof.isoformat(),'coverage_status':status,'selected_count':len(final),'target_per_chapter':target,
      'duplicate_groups_resolved':duplicate_groups,'removed_count':len(removed),'backfilled':backfilled,
      'cross_chapter_duplicate_urls':cross_duplicates,'chapter_report':report,'selected':final
    }


def self_test():
    now='2026-09-02T00:00:00+00:00'
    candidates=[]
    seeds={
      '국제 · 외교 · 안보':('iran','intl'),
      '과학':('research','science'),
      '경제 · 시장':('inflation','economy'),
      '국내·해외 주식 · 이슈기업':('earnings','stocks'),
    }
    for ch,(kw,slug) in seeds.items():
        for d in range(5):
            for j in range(3):
                candidates.append({'chapter':ch,'title':f'{kw} unique{d}{j} event{d}{j} signal{d}{j}','summary':kw,'url':f'https://s{d}.example/{slug}/{j}','domain':f's{d}.example','published':now,'tier':2,'source':'Gold'})
    shared='https://news.example/shein'
    candidates += [
      {'chapter':'경제 · 시장','title':'Shein stock market IPO debut','summary':'market','url':shared,'domain':'news.example','published':now,'tier':2,'source':'News'},
      {'chapter':'국내·해외 주식 · 이슈기업','title':'Shein IPO stock market debut','summary':'ipo','url':shared,'domain':'news.example','published':now,'tier':2,'source':'News'}]
    base_sel=base.select({'generated_at':now,'candidates':candidates},10,now)
    out=arbitrate({'generated_at':now,'candidates':candidates},base_sel)
    assert len(out['duplicate_groups_resolved'])==1,out
    assert out['duplicate_groups_resolved'][0]['winner']=='국내·해외 주식 · 이슈기업',out
    assert not out['cross_chapter_duplicate_urls'],out
    assert out['coverage_status']=='PASS',out
    print('PASS: global priority arbitration self-test')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--candidates');ap.add_argument('--selected');ap.add_argument('--output');ap.add_argument('--target',type=int,default=TARGET);ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
    if a.self_test:self_test();return 0
    if not all([a.candidates,a.selected,a.output]):ap.error('--candidates --selected --output required')
    c=json.loads(Path(a.candidates).read_text(encoding='utf-8'));s=json.loads(Path(a.selected).read_text(encoding='utf-8'));out=arbitrate(c,s,a.target)
    p=Path(a.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"ARBITRATION selected={out['selected_count']} duplicates_resolved={len(out['duplicate_groups_resolved'])} backfilled={len(out['backfilled'])} coverage={out['coverage_status']}")
    for x in out['duplicate_groups_resolved']:print(' DUPLICATE',x)
    for ch,r in out['chapter_report'].items():print(' ',ch,r)
    return 0 if out['coverage_status']=='PASS' else 2
if __name__=='__main__':sys.exit(main())
