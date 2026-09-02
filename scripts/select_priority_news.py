#!/usr/bin/env python3
import argparse, json, re, sys
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

POLICY = {
    '국제 · 외교 · 안보': {
        'max_age_days': 3,
        'keywords': ['iran','russia','ukraine','g20','nato','china','taiwan','war','strike','missile','drone','sanction','security','defense','defence','diplom','government','border','nuclear','ceasefire','military','trade war','venezuela'],
        'exclude': ['football','rugby','tour','singer','actor','arcade','game','celebrity','baseball','trial deadlocked','cold case'],
    },
    '과학': {
        'max_age_days': 7,
        'keywords': ['nasa','space','mars','moon','earth','climate','science','research','study','particle','physics','astronomy','telescope','glacier','ocean','weather','solar','quantum','genome','biology','iceberg','mission','satellite','cyclone'],
        'exclude': ['sports','football','celebrity','game','shopping'],
    },
    '경제 · 시장': {
        'max_age_days': 7,
        'keywords': ['rate','inflation','gdp','jobs','employment','economy','economic','market','yield','oil','energy','lng','trade','export','import','central bank','federal reserve','ecb','bank of korea','bea','eia','consumer','production','manufacturing','uranium'],
        'exclude': ['museum','exhibition','podcast','webcast','collection','cbdc'],
    },
    '국내·해외 주식 · 이슈기업': {
        'max_age_days': 7,
        'keywords': ['earnings','revenue','forecast','guidance','shares','stock','acquisition','acquire','merger','investment','invest','shipping','launch','introduces','unveils','contract','partnership','ceo','manufacturing','production','available','capacity'],
        'exclude': ['arcade','baseball','friday night','travel','maps','skywatching'],
    },
}
TARGET = 10
MIN_DOMAINS = 5
MAX_PER_DOMAIN = 2
GENERIC_PATHS = {'','/','/news','/world','/business','/technology','/research-highlights'}

def parse_dt(v):
    if not v: return None
    try:
        if re.match(r'^\d{4}-\d{2}-\d{2}T', v):
            return datetime.fromisoformat(v.replace('Z','+00:00')).astimezone(timezone.utc)
        return parsedate_to_datetime(v).astimezone(timezone.utc)
    except Exception:
        return None

def norm_title(s):
    return re.sub(r'[^a-z0-9가-힣]+',' ',(s or '').lower()).strip()

def similar(a,b):
    A=set(norm_title(a).split()); B=set(norm_title(b).split())
    if not A or not B: return False
    return len(A&B)/len(A|B) >= .72

def score(c, asof):
    pol=POLICY[c['chapter']]
    text=(c.get('title','')+' '+c.get('summary','')).lower()
    if any(x in text for x in pol['exclude']): return None, 'excluded_topic'
    rel=sum(1 for x in pol['keywords'] if x in text)
    if rel < 1: return None, 'low_relevance'
    dt=parse_dt(c.get('published'))
    if not dt: return None, 'missing_date'
    age=(asof-dt).total_seconds()/86400
    if age < -1: return None, 'future_date'
    if age > pol['max_age_days']: return None, 'stale'
    u=urlparse(c.get('url',''))
    if u.scheme not in ('http','https') or not u.netloc: return None, 'bad_url'
    if u.path.rstrip('/') in GENERIC_PATHS: return None, 'generic_url'
    freshness=max(0, pol['max_age_days']-max(0,age))
    tier=max(0,4-int(c.get('tier',4)))
    return rel*10 + freshness*2 + tier, None

def select(data, target=TARGET):
    candidates=data.get('candidates',[])
    dts=[parse_dt(x.get('published')) for x in candidates]
    dts=[d for d in dts if d]
    asof=max(dts) if dts else datetime.now(timezone.utc)
    selected_all=[]; reports={}; rejected=Counter()
    for chapter in POLICY:
        ranked=[]
        for c in candidates:
            if c.get('chapter') != chapter: continue
            s,reason=score(c,asof)
            if reason:
                rejected[(chapter,reason)] += 1; continue
            ranked.append((s,parse_dt(c.get('published')),c))
        ranked.sort(key=lambda z:(z[0],z[1]), reverse=True)
        chosen=[]; domain_counts=Counter()
        for s,dt,c in ranked:
            dom=c.get('domain') or urlparse(c.get('url','')).netloc.lower().removeprefix('www.')
            if domain_counts[dom] >= MAX_PER_DOMAIN: continue
            if any(similar(c.get('title'),x.get('title')) for x in chosen): continue
            item=dict(c); item['selection_score']=round(s,2); item['selection_reason']='fresh_relevant_diverse'
            chosen.append(item); domain_counts[dom]+=1
            if len(chosen)>=target: break
        domains=len(domain_counts)
        status='PASS' if len(chosen)>=target and domains>=MIN_DOMAINS else 'FAIL'
        reports[chapter]={
            'eligible_count':len(ranked),'selected_count':len(chosen),'unique_domains':domains,
            'domain_counts':dict(domain_counts),'status':status,
            'reject_counts':{reason:n for (ch,reason),n in rejected.items() if ch==chapter},
        }
        selected_all.extend(chosen)
    overall='PASS' if all(r['status']=='PASS' for r in reports.values()) else 'FAIL'
    return {
        'schema_version':'priority-news-selection-v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'candidate_count':len(candidates),'selected_count':len(selected_all),'target_per_chapter':target,
        'minimum_unique_domains':MIN_DOMAINS,'max_per_domain':MAX_PER_DOMAIN,
        'coverage_status':overall,'chapter_report':reports,'selected':selected_all,
    }

def self_test():
    now=datetime(2026,9,2,tzinfo=timezone.utc)
    cs=[]
    for ch,pol in POLICY.items():
        kw=pol['keywords'][0]
        for d in range(5):
            for j in range(2):
                uniq=['alpha','bravo','charlie','delta','echo'][d] + ('-one' if j==0 else '-two')
                cs.append({'chapter':ch,'title':f'{kw} {uniq} important update','summary':kw,'url':f'https://s{d}.example.com/a/{j}','domain':f's{d}.example.com','published':now.isoformat(),'tier':1,'source':f'S{d}'})
    out=select({'candidates':cs})
    assert out['coverage_status']=='PASS', out
    bad={'chapter':'국제 · 외교 · 안보','title':'football celebrity tour','summary':'sports','url':'https://x.example/a','domain':'x.example','published':now.isoformat(),'tier':2,'source':'X'}
    x=select({'candidates':[bad]})
    assert x['coverage_status']=='FAIL'
    print('PASS: priority-news selector self-test')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input'); ap.add_argument('--output'); ap.add_argument('--target',type=int,default=TARGET); ap.add_argument('--self-test',action='store_true')
    a=ap.parse_args()
    if a.self_test: self_test(); return 0
    if not a.input or not a.output: ap.error('--input and --output required')
    data=json.loads(Path(a.input).read_text(encoding='utf-8')); out=select(data,a.target)
    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"WROTE {p}: selected {out['selected_count']} / coverage={out['coverage_status']}")
    for ch,r in out['chapter_report'].items(): print(' ',ch,r)
    return 0 if out['coverage_status']=='PASS' else 2

if __name__=='__main__': sys.exit(main())
