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


def item_domain(item):
    return item.get('domain') or urlsplit(item.get('canonical_url') or item.get('url','')).netloc.lower().removeprefix('www.')


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
    ranked=[]; score_rejects=Counter()
    for c in candidates:
        if c.get('chapter') != chapter:
            continue
        score,reason=base.score(c,asof)
        if reason:
            score_rejects[reason]+=1
            continue
        ranked.append((score,base.parse_dt(c.get('published')),c))
    ranked.sort(key=lambda z:(z[0],z[1]),reverse=True)
    return ranked,score_rejects


def add_rejection_reason(chosen, candidate, globally_used):
    key=canonical_key(candidate.get('canonical_url') or candidate.get('url'))
    if not key:
        return 'missing_url'
    if key in globally_used:
        return 'global_url'
    domain=item_domain(candidate)
    if Counter(item_domain(x) for x in chosen)[domain] >= base.MAX_PER_DOMAIN:
        return 'domain_cap'
    if any(base.same_event(candidate.get('title'),x.get('title')) for x in chosen):
        return 'same_event'
    return ''


def valid_add(chosen, candidate, globally_used):
    return not add_rejection_reason(chosen,candidate,globally_used)


def refill_chapter(chosen, ranked, globally_used, target):
    """Fill a chapter after cross-chapter removals without relaxing base quality.

    Pass 1 preserves every surviving selected item. If that cannot reach target,
    pass 2 re-solves the chapter from the full ranked eligible pool while keeping
    globally-owned URLs from other chapters excluded. This allows a different
    combination of same-event/domain candidates to satisfy the quota rather than
    getting trapped by greedy survivor ordering.
    """
    rejects=Counter(); added=[]
    for score,published,c in ranked:
        if len(chosen)>=target: break
        reason=add_rejection_reason(chosen,c,globally_used)
        if reason:
            rejects[reason]+=1; continue
        item=dict(c); item['selection_score']=round(score,2); item['selection_reason']='global_arbitration_backfill'
        chosen.append(item); globally_used.add(canonical_key(item.get('canonical_url') or item.get('url')))
        added.append(item)
    if len(chosen)>=target:
        return chosen,globally_used,added,rejects,False

    # Remove this chapter's URLs from the global set, then solve the chapter again
    # from the complete quality-qualified ranking. Other chapters remain reserved.
    for x in chosen:
        globally_used.discard(canonical_key(x.get('canonical_url') or x.get('url')))
    rebuilt=[]; rebuilt_added=[]; second_rejects=Counter()
    for score,published,c in ranked:
        if len(rebuilt)>=target: break
        reason=add_rejection_reason(rebuilt,c,globally_used)
        if reason:
            second_rejects[reason]+=1; continue
        item=dict(c); item['selection_score']=round(score,2); item['selection_reason']='global_arbitration_constrained_refill'
        rebuilt.append(item); globally_used.add(canonical_key(item.get('canonical_url') or item.get('url')))
        rebuilt_added.append(item)
    rejects.update({f'resolve_{k}':v for k,v in second_rejects.items()})
    return rebuilt,globally_used,rebuilt_added,rejects,True


def arbitrate(candidate_data, selected_data, target=TARGET):
    asof=base.resolve_asof(candidate_data, selected_data.get('as_of'))
    selected=[dict(x) for x in selected_data.get('selected',[])]
    by_url=defaultdict(list)
    for item in selected:
        by_url[canonical_key(item.get('canonical_url') or item.get('url'))].append(item)

    removed=[]; kept=[]; duplicate_groups=[]
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
    for item in kept: by_chapter[item['chapter']].append(item)
    globally_used={canonical_key(x.get('canonical_url') or x.get('url')) for x in kept}
    backfilled=[]; refill_diagnostics={}

    for chapter in base.POLICY:
        chosen=by_chapter[chapter]
        ranked,score_rejects=rank_candidates(candidate_data.get('candidates',[]),chapter,asof)
        if len(chosen)<target:
            old_keys={canonical_key(x.get('canonical_url') or x.get('url')) for x in chosen}
            chosen,globally_used,added,rejects,re_solved=refill_chapter(chosen,ranked,globally_used,target)
            by_chapter[chapter]=chosen
            for item in added:
                key=canonical_key(item.get('canonical_url') or item.get('url'))
                if key not in old_keys:
                    backfilled.append({'chapter':chapter,'title':item.get('title'),'url':item.get('url'),'mode':item.get('selection_reason')})
            refill_diagnostics[chapter]={
                'eligible_ranked_count':len(ranked),'score_reject_counts':dict(score_rejects),
                'constraint_reject_counts':dict(rejects),'constrained_resolve_used':re_solved,
                'final_count':len(chosen),
            }

    final=[]; report={}
    for chapter in base.POLICY:
        chosen=by_chapter[chapter]
        domains=Counter(item_domain(x) for x in chosen)
        status='PASS' if len(chosen)>=target and len(domains)>=base.MIN_DOMAINS else 'FAIL'
        report[chapter]={'selected_count':len(chosen),'unique_domains':len(domains),'domain_counts':dict(domains),'status':status}
        final.extend(chosen)

    keys=[canonical_key(x.get('canonical_url') or x.get('url')) for x in final]
    cross_duplicates=[k for k,n in Counter(keys).items() if k and n>1]
    status='PASS' if all(x['status']=='PASS' for x in report.values()) and not cross_duplicates and len(final)==target*len(base.POLICY) else 'FAIL'
    return {
      'schema_version':'priority-news-global-arbitration-v2','generated_at':base.datetime.now(base.timezone.utc).isoformat(),
      'as_of':asof.isoformat(),'coverage_status':status,'selected_count':len(final),'target_per_chapter':target,
      'duplicate_groups_resolved':duplicate_groups,'removed_count':len(removed),'backfilled':backfilled,
      'refill_diagnostics':refill_diagnostics,'cross_chapter_duplicate_urls':cross_duplicates,'chapter_report':report,'selected':final
    }


def _fixture_item(ch,kw,slug,d,j,now):
    return {'chapter':ch,'title':f'{kw} unique{d}{j} event{d}{j} signal{d}{j}','summary':kw,'url':f'https://s{d}.example/{slug}/{j}','domain':f's{d}.example','published':now,'tier':2,'source':'Gold'}


def self_test():
    now='2026-09-02T00:00:00+00:00'; candidates=[]; selected=[]
    seeds={'국제 · 외교 · 안보':('iran','intl'),'과학':('research','science'),'경제 · 시장':('inflation','economy'),'국내·해외 주식 · 이슈기업':('earnings','stocks')}
    for ch,(kw,slug) in seeds.items():
        for d in range(5):
            for j in range(3):
                item=_fixture_item(ch,kw,slug,d,j,now); candidates.append(item)
                if j < 2: selected.append(dict(item))
    shared='https://news.example/shein'
    economy_shared={'chapter':'경제 · 시장','title':'Shein stock market IPO debut','summary':'market inflation','url':shared,'domain':'news.example','published':now,'tier':2,'source':'News'}
    stocks_shared={'chapter':'국내·해외 주식 · 이슈기업','title':'Shein IPO stock market debut','summary':'ipo earnings','url':shared,'domain':'news.example','published':now,'tier':2,'source':'News'}
    candidates.extend([economy_shared,stocks_shared])
    selected=[x for x in selected if not (x['chapter']=='경제 · 시장' and x['url']=='https://s4.example/economy/1')]
    selected=[x for x in selected if not (x['chapter']=='국내·해외 주식 · 이슈기업' and x['url']=='https://s4.example/stocks/1')]
    selected.extend([economy_shared,stocks_shared])
    out=arbitrate({'generated_at':now,'candidates':candidates},{'as_of':now,'selected':selected})
    assert len(out['duplicate_groups_resolved'])==1,out
    assert out['duplicate_groups_resolved'][0]['winner']=='국내·해외 주식 · 이슈기업',out
    assert out['coverage_status']=='PASS' and out['selected_count']==40,out
    assert out['chapter_report']['경제 · 시장']['selected_count']==10,out

    # Regression: two cross-chapter duplicate losses from economy must be refillable
    # from the full quality-qualified economy ranking without lowering thresholds.
    candidates2=[dict(x) for x in candidates]; selected2=[dict(x) for x in selected if canonical_key(x.get('url'))!=canonical_key(shared)]
    shared2='https://news.example/g20'
    intl2={'chapter':'국제 · 외교 · 안보','title':'G20 leaders discuss security tensions','summary':'security diplomacy','url':shared2,'domain':'news.example','published':now,'tier':2,'source':'News'}
    econ2={'chapter':'경제 · 시장','title':'G20 leaders discuss security tensions','summary':'inflation market','url':shared2,'domain':'news.example','published':now,'tier':2,'source':'News'}
    candidates2.extend([intl2,econ2])
    # Make selected lists exactly ten/chapter and inject two economy duplicates.
    by=defaultdict(list)
    for x in selected2: by[x['chapter']].append(x)
    by['국제 · 외교 · 안보']=by['국제 · 외교 · 안보'][:9]+[intl2]
    by['경제 · 시장']=by['경제 · 시장'][:8]+[economy_shared,econ2]
    by['국내·해외 주식 · 이슈기업']=by['국내·해외 주식 · 이슈기업'][:9]+[stocks_shared]
    selected2=[x for ch in base.POLICY for x in by[ch][:10]]
    candidates2.extend([economy_shared,stocks_shared])
    out2=arbitrate({'generated_at':now,'candidates':candidates2},{'as_of':now,'selected':selected2})
    assert len(out2['duplicate_groups_resolved'])>=2,out2
    assert out2['coverage_status']=='PASS' and out2['selected_count']==40,out2
    assert out2['chapter_report']['경제 · 시장']['selected_count']==10,out2
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
    for ch,d in out['refill_diagnostics'].items():print(' REFILL',ch,d)
    return 0 if out['coverage_status']=='PASS' else 2
if __name__=='__main__':sys.exit(main())
