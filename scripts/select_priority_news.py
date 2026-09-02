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
        'exclude': ['sports','football','celebrity','game','shopping','apod','skywatching tips','what s up'],
    },
    '경제 · 시장': {
        'max_age_days': 7,
        'keywords': ['rate','rates','inflation','gdp','jobs','employment','economy','economic','market','markets','yield','yields','oil','energy','lng','trade','exports','export','imports','import','central bank','federal reserve','ecb','bank of korea','bea','eia','consumer','consumers','production','manufacturing','uranium','bond','bonds','tariff','tariffs','currency','dollar','growth','recession'],
        'exclude': ['museum','exhibition','podcast','webcast','collection','cbdc','apple maps','google maps','lake america'],
    },
    '국내·해외 주식 · 이슈기업': {
        'max_age_days': 7,
        'keywords': ['earnings','revenue','profit','profits','forecast','guidance','shares','stock','stocks','acquisition','acquire','acquires','merger','investment','invests','invested','funding','fundraise','fundraising','raises','raised','secures','secured','series a','series b','series c','valuation','valued','ipo','initial public offering','sale','sells','sold','shipping','launch','launches','launched','introduces','unveils','contract','partnership','ceo','manufacturing','production','capacity','layoffs','jobs cut','factory'],
        'exclude': ['arcade','baseball','friday night','travel','maps','skywatching','air strike','airstrikes','drone attack','missile attack','sanctions on russia','funding bill','government shutdown','house passes','congress passes'],
    },
}
TARGET = 10
MIN_DOMAINS = 5
MAX_PER_DOMAIN = 2
GENERIC_PATHS = {'','/','/news','/world','/business','/technology','/research-highlights'}
STOCK_STRONG_TITLE_TERMS = [
    'earnings','revenue','profit','forecast','guidance','shares','stock','acquisition','acquire','acquires','merger',
    'investment','invests','funding','fundraise','fundraising','raises','raised','secures','secured','series a','series b','series c',
    'ipo','initial public offering','valued','valuation','sale','sells','sold','shipping','introduces','unveils','contract','partnership',
    'ceo','manufacturing','production','capacity','layoffs','jobs cut','factory','electric model','cpu','gpu','chip','chips','data center','datacenter'
]
ECONOMY_STRONG_TITLE_TERMS = [
    'inflation','gdp','jobs','employment','economy','economic','market','markets','bond','bonds','yield','yields','oil','energy','lng',
    'trade','tariff','tariffs','central bank','federal reserve','fed chair','bank of england','bank of korea','interest rate','interest rates',
    'consumer spending','retail sales','manufacturing','production','currency','dollar','growth','recession','g20','uranium production'
]
LOW_IMPACT_PRIMARY_PATTERNS = [
    'supports','now supports','now lets you','now available','available in additional','adds support for','console update','backup now','version update'
]
ECONOMY_LOW_IMPACT_PRIMARY = ['enforcement action','former employee','civil money penalty','prohibition order']

STOPWORDS = {
    'a','an','and','are','as','at','after','ahead','amid','be','been','by','for','from','has','have','in','into','is','it','its','new','of','on','or','over','says','say','the','their','this','to','with','will','us','u','s',
    'report','reports','reported','moment','video','watch','powerful','historic','rare','first','next','generation','beginning','future','state','media'
}
EVENT_ACTION_TOKENS = {
    'launch','strike','attack','drone','wedding','groundbreak','telescope','sanction','trade','war','deport','border','bond','inflation','downturn','production','fab','ipo','acquisition','funding','valuation','supercomputer'
}
TOKEN_ALIASES = {
    'launches':'launch','launched':'launch','launching':'launch',
    'strikes':'strike','struck':'strike','attacks':'attack','attacked':'attack',
    'drones':'drone','sanctions':'sanction','deportees':'deport','deported':'deport',
    'iranian':'iran','russian':'russia','german':'germany',
    'groundbreaking':'groundbreak','groundbreakings':'groundbreak',
    'telescopes':'telescope','markets':'market','bonds':'bond','tariffs':'tariff',
}

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
    text=' '+norm_title(text)+' '
    term=norm_title(term)
    if not term: return False
    return (' '+term+' ') in text

def count_terms(text, terms):
    return sum(1 for t in terms if term_match(text,t))

def event_tokens(title):
    text=norm_title(title)
    text=re.sub(r'\bbreaks? ground\b',' groundbreak ',text)
    text=re.sub(r'\bground breaking\b',' groundbreak ',text)
    out=[]
    for tok in text.split():
        tok=TOKEN_ALIASES.get(tok,tok)
        if len(tok) < 3 or tok in STOPWORDS or tok.isdigit():
            continue
        out.append(tok)
    return set(out)

def same_event(a,b):
    A=event_tokens(a); B=event_tokens(b)
    if not A or not B: return False
    common=A & B
    if len(common) < 3: return False
    containment=len(common)/min(len(A),len(B))
    jaccard=len(common)/len(A|B)
    action=bool(common & EVENT_ACTION_TOKENS)
    return (action and containment >= .34) or jaccard >= .45

def valid_url(raw):
    u=urlparse(raw or '')
    if u.scheme not in ('http','https') or not u.netloc: return False, 'bad_url'
    if u.path.rstrip('/') in GENERIC_PATHS: return False, 'generic_url'
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

    tier=int(c.get('tier',4))
    if chapter == '경제 · 시장':
        if tier >= 2 and count_terms(title, ECONOMY_STRONG_TITLE_TERMS) < 1:
            return None, 'weak_macro_signal'
        if tier <= 1 and any(term_match(title,x) for x in ECONOMY_LOW_IMPACT_PRIMARY):
            return None, 'low_impact_primary_update'

    if chapter == '국내·해외 주식 · 이슈기업':
        if tier >= 2 and count_terms(title, STOCK_STRONG_TITLE_TERMS) < 1:
            return None, 'weak_company_signal'
        if tier <= 1 and any(term_match(title,x) for x in LOW_IMPACT_PRIMARY_PATTERNS):
            return None, 'low_impact_primary_update'

    dt=parse_dt(c.get('published'))
    if not dt: return None, 'missing_date'
    age=(asof-dt).total_seconds()/86400
    if age < -1: return None, 'future_date'
    if age > pol['max_age_days']: return None, 'stale'
    ok,reason=valid_url(c.get('url',''))
    if not ok: return None, reason
    freshness=max(0, pol['max_age_days']-max(0,age))
    trust=max(0,4-tier)
    return rel*10 + freshness*2 + trust, None

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
        chosen=[]; domain_counts=Counter(); event_dupes=0
        for s,dt,c in ranked:
            dom=c.get('domain') or urlparse(c.get('url','')).netloc.lower().removeprefix('www.')
            if domain_counts[dom] >= MAX_PER_DOMAIN: continue
            if any(same_event(c.get('title'),x.get('title')) for x in chosen):
                event_dupes += 1
                continue
            item=dict(c); item['selection_score']=round(s,2); item['selection_reason']='fresh_relevant_diverse_event_unique_complete_url'
            chosen.append(item); domain_counts[dom]+=1
            if len(chosen)>=target: break
        domains=len(domain_counts)
        status='PASS' if len(chosen)>=target and domains>=MIN_DOMAINS else 'FAIL'
        reports[chapter]={
            'eligible_count':len(ranked),'selected_count':len(chosen),'unique_domains':domains,
            'domain_counts':dict(domain_counts),'event_duplicates_skipped':event_dupes,'status':status,
            'reject_counts':{reason:n for (ch,reason),n in rejected.items() if ch==chapter},
        }
        selected_all.extend(chosen)
    overall='PASS' if all(r['status']=='PASS' for r in reports.values()) else 'FAIL'
    return {
        'schema_version':'priority-news-selection-v4','generated_at':datetime.now(timezone.utc).isoformat(),
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
                uniq=f'event{d}{j} topic{d}{j} signal{d}{j}'
                cs.append({'chapter':ch,'title':f'{kw} {uniq}','summary':kw,'url':f'https://s{d}.example.com/a/{j}','domain':f's{d}.example.com','published':now.isoformat(),'tier':2,'source':f'S{d}'})
    out=select({'candidates':cs})
    assert out['coverage_status']=='PASS', out

    assert count_terms('corporate celebration', ['rate']) == 0
    assert valid_url('https://www.eia.gov/todayinenergy/detail.php?id=')[0] is False

    geo={'chapter':'국내·해외 주식 · 이슈기업','title':'US launches new strikes on Iran','summary':'military attack','url':'https://news.example/x','domain':'news.example','published':now.isoformat(),'tier':2,'source':'News'}
    assert score(geo,now)[0] is None
    political={'chapter':'국내·해외 주식 · 이슈기업','title':'Leader makes House of Commons debut','summary':'politics','url':'https://news.example/y','domain':'news.example','published':now.isoformat(),'tier':2,'source':'News'}
    assert score(political,now)[0] is None
    govt_funding={'chapter':'국내·해외 주식 · 이슈기업','title':'US House passes funding bill to avert government shutdown','summary':'congress','url':'https://news.example/g','domain':'news.example','published':now.isoformat(),'tier':2,'source':'News'}
    assert score(govt_funding,now)[0] is None
    booking={'chapter':'경제 · 시장','title':"Fake 10 Downing Street listing exposes unfit Booking.com, says consumer group",'summary':'consumer complaint','url':'https://news.example/b','domain':'news.example','published':now.isoformat(),'tier':2,'source':'News'}
    assert score(booking,now)[0] is None
    enforcement={'chapter':'경제 · 시장','title':'Federal Reserve Board issues enforcement action with former employee of Banco Popular','summary':'federal reserve','url':'https://fed.example/e','domain':'fed.example','published':now.isoformat(),'tier':0,'source':'Fed'}
    assert score(enforcement,now)[0] is None
    apod={'chapter':'과학','title':'APOD: Launch of the Roman Space Telescope','summary':'space telescope','url':'https://science.example/apod','domain':'science.example','published':now.isoformat(),'tier':1,'source':'NASA'}
    assert score(apod,now)[0] is None
    sky={'chapter':'과학','title':'What’s Up: September 2026 Skywatching Tips from NASA','summary':'space','url':'https://science.example/sky','domain':'science.example','published':now.isoformat(),'tier':1,'source':'NASA'}
    assert score(sky,now)[0] is None

    funding={'chapter':'국내·해외 주식 · 이슈기업','title':'AIR raises $50M in funding for AI security platform','summary':'startup funding','url':'https://tech.example/z','domain':'tech.example','published':now.isoformat(),'tier':3,'source':'Tech'}
    assert score(funding,now)[0] is not None
    maintenance={'chapter':'국내·해외 주식 · 이슈기업','title':'Cloud service supports database version 3.3.1','summary':'production support','url':'https://company.example/a','domain':'company.example','published':now.isoformat(),'tier':1,'source':'Company'}
    assert score(maintenance,now)[0] is None

    assert same_event('Germany blames Russia for airport drone incident, hits back with sanctions','Germany says Russia behind attempted drone attack at Leipzig airport')
    assert same_event('Iran retaliates after US strikes kill four at wedding party','Moment US strikes on Iranian port city hit wedding party')
    assert same_event('NASA’s Nancy Grace Roman Space Telescope Launches','Nasa launches powerful new space telescope')
    assert same_event('AI could cause global economic downturn, Andrew Bailey warns G20','AI could cause global economic downturn, Bank of England governor tells G20')
    assert same_event('SK hynix Indiana fab breaks ground as new hub for US AI innovation','SK hynix Holds Groundbreaking Ceremony for HBM Production Base in Indiana')
    assert not same_event('US launches new strikes on Iran','Iran retaliates after US strikes kill four at wedding party')

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
