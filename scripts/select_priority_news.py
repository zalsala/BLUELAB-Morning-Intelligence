#!/usr/bin/env python3
import argparse, json, re, sys
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

POLICY = {
    '국제 · 외교 · 안보': {
        'max_age_days': 3,
        'keywords': ['iran','russia','ukraine','g20','nato','china','taiwan','war','strike','strikes','missile','drone','sanction','sanctions','security','defense','defence','diplomacy','diplomatic','government','border','nuclear','ceasefire','military','trade war','venezuela'],
        'exclude': ['football','rugby','tour','singer','actor','arcade','game','celebrity','baseball','trial deadlocked','cold case'],
    },
    '과학': {
        'max_age_days': 7,
        'keywords': ['nasa','space','mars','moon','earth','climate','science','scientific','research','study','particle','physics','astronomy','telescope','glacier','ocean','weather','solar','quantum','genome','biology','iceberg','mission','satellite','cyclone'],
        'exclude': ['sports','football','celebrity','game','shopping'],
    },
    '경제 · 시장': {
        'max_age_days': 7,
        'keywords': ['rate','rates','inflation','gdp','jobs','employment','economy','economic','market','markets','yield','yields','oil','energy','lng','trade','exports','export','imports','import','central bank','federal reserve','ecb','bank of korea','bea','eia','consumer','consumers','production','manufacturing','uranium','bond','bonds','tariff','tariffs','currency','dollar','growth','recession'],
        'exclude': ['museum','exhibition','podcast','webcast','collection','cbdc','apple maps','google maps','lake america'],
    },
    '국내·해외 주식 · 이슈기업': {
        'max_age_days': 7,
        'keywords': ['earnings','revenue','profit','profits','forecast','guidance','shares','stock','stocks','acquisition','acquire','acquires','merger','investment','invests','invested','shipping','launch','launches','launched','introduces','unveils','contract','partnership','ceo','manufacturing','production','capacity','ipo','debut','valued','valuation','layoffs','jobs cut','factory'],
        'exclude': ['arcade','baseball','friday night','travel','maps','skywatching','air strike','airstrikes','drone attack','missile attack','sanctions on russia'],
    },
}
TARGET = 10
MIN_DOMAINS = 5
MAX_PER_DOMAIN = 2
GENERIC_PATHS = {'','/','/news','/world','/business','/technology','/research-highlights'}
STOCK_STRONG_TITLE_TERMS = [
    'earnings','revenue','profit','forecast','guidance','shares','stock','acquisition','acquire','acquires','merger',
    'investment','invests','shipping','launch','launches','launched','introduces','unveils','contract','partnership',
    'ceo','manufacturing','production','capacity','ipo','debut','valued','valuation','layoffs','jobs cut','factory',
    'electric model','cpu','gpu','chip','chips','data center','datacenter'
]
LOW_IMPACT_PRIMARY_PATTERNS = [
    'now supports','now lets you','now available','available in additional','adds support for','console update','backup now'
]

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

def term_match(text, term):
    """Match complete words/phrases, preventing substring false positives."""
    text=' '+norm_title(text)+' '
    term=norm_title(term)
    if not term: return False
    return (' '+term+' ') in text

def count_terms(text, terms):
    return sum(1 for t in terms if term_match(text,t))

def similar(a,b):
    A=set(norm_title(a).split()); B=set(norm_title(b).split())
    if not A or not B: return False
    return len(A&B)/len(A|B) >= .72

def valid_url(raw):
    u=urlparse(raw or '')
    if u.scheme not in ('http','https') or not u.netloc: return False, 'bad_url'
    if u.path.rstrip('/') in GENERIC_PATHS: return False, 'generic_url'
    # Known detail endpoints must contain a non-empty record identifier.
    if u.netloc.endswith('eia.gov') and u.path.endswith('/todayinenergy/detail.php'):
        if not parse_qs(u.query).get('id'): return False, 'incomplete_url'
    if raw.endswith('?') or re.search(r'[?&](?:id|article|story)=?$', raw):
        return False, 'incomplete_url'
    return True, None

def score(c, asof):
    chapter=c['chapter']; pol=POLICY[chapter]
    title=c.get('title',''); summary=c.get('summary',''); text=title+' '+summary
    if any(term_match(text,x) for x in pol['exclude']): return None, 'excluded_topic'
    rel=count_terms(text, pol['keywords'])
    if rel < 1: return None, 'low_relevance'

    if chapter == '국내·해외 주식 · 이슈기업':
        # General media must have an explicit corporate/market signal in the headline.
        # Primary company sources may qualify through major product/partnership news,
        # but small operational feature updates are excluded.
        if int(c.get('tier',4)) >= 2 and count_terms(title, STOCK_STRONG_TITLE_TERMS) < 1:
            return None, 'weak_company_signal'
        if int(c.get('tier',4)) <= 1 and any(term_match(title,x) for x in LOW_IMPACT_PRIMARY_PATTERNS):
            return None, 'low_impact_primary_update'

    dt=parse_dt(c.get('published'))
    if not dt: return None, 'missing_date'
    age=(asof-dt).total_seconds()/86400
    if age < -1: return None, 'future_date'
    if age > pol['max_age_days']: return None, 'stale'
    ok,reason=valid_url(c.get('url',''))
    if not ok: return None, reason
    freshness=max(0, pol['max_age_days']-max(0,age))
    tier=max(0,4-int(c.get('tier',4)))
    # Multiple independent relevance signals outrank one accidental mention.
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
            item=dict(c); item['selection_score']=round(s,2); item['selection_reason']='fresh_relevant_diverse_complete_url'
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
        'schema_version':'priority-news-selection-v2','generated_at':datetime.now(timezone.utc).isoformat(),
        'candidate_count':len(candidates),'selected_count':len(selected_all),'target_per_chapter':target,
        'minimum_unique_domains':MIN_DOMAINS,'max_per_domain':MAX_PER_DOMAIN,
        'coverage_status':overall,'chapter_report':reports,'selected':selected_all,
    }

def self_test():
    now=datetime(2026,9,2,tzinfo=timezone.utc)
    cs=[]
    seed_terms={
        '국제 · 외교 · 안보':'iran',
        '과학':'research',
        '경제 · 시장':'inflation',
        '국내·해외 주식 · 이슈기업':'earnings',
    }
    for ch in POLICY:
        kw=seed_terms[ch]
        for d in range(5):
            for j in range(2):
                uniq=['alpha','bravo','charlie','delta','echo'][d] + (' one' if j==0 else ' two')
                cs.append({'chapter':ch,'title':f'{kw} {uniq} company update','summary':kw,'url':f'https://s{d}.example.com/a/{j}','domain':f's{d}.example.com','published':now.isoformat(),'tier':2,'source':f'S{d}'})
    out=select({'candidates':cs})
    assert out['coverage_status']=='PASS', out
    bad={'chapter':'국제 · 외교 · 안보','title':'football celebrity tour','summary':'sports','url':'https://x.example/a','domain':'x.example','published':now.isoformat(),'tier':2,'source':'X'}
    assert select({'candidates':[bad]})['coverage_status']=='FAIL'
    # Boundary check: "rate" must not match arbitrary words containing those letters.
    assert count_terms('corporate celebration', ['rate']) == 0
    # Incomplete EIA record URL must be rejected.
    assert valid_url('https://www.eia.gov/todayinenergy/detail.php?id=')[0] is False
    # Geopolitical "launches strikes" must not become a stock story merely because of launch wording.
    geo={'chapter':'국내·해외 주식 · 이슈기업','title':'US launches new strikes on Iran','summary':'military attack','url':'https://news.example/x','domain':'news.example','published':now.isoformat(),'tier':2,'source':'News'}
    assert score(geo,now)[0] is None
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
