#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, sys, time, urllib.error, urllib.request, xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'config'/'youtube-signals.json'
UA='BLUELAB-Morning-Intelligence/1.0 (+https://github.com/zalsala/BLUELAB-Morning-Intelligence)'
TIMEOUT=20
ATOM='http://www.w3.org/2005/Atom'
YT='http://www.youtube.com/xml/schemas/2015'
RETRYABLE={429,500,502,503,504}

def now(): return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
def parse_dt(v):
    try: return dt.datetime.fromisoformat((v or '').replace('Z','+00:00')).astimezone(dt.timezone.utc)
    except Exception: return None

def endpoints(channel_id):
    suffix=channel_id[2:] if channel_id.startswith('UC') else channel_id
    return [
      ('channel',f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'),
      ('uploads',f'https://www.youtube.com/feeds/videos.xml?playlist_id=UU{suffix}'),
      ('shorts',f'https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH{suffix}'),
    ]

def request(url,retries=3):
    last=None
    for attempt in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/atom+xml, application/xml;q=0.9, */*;q=0.5'})
            with urllib.request.urlopen(req,timeout=TIMEOUT) as r: return r.read()
        except urllib.error.HTTPError as exc:
            last=exc
            if exc.code not in RETRYABLE: break
        except (urllib.error.URLError, TimeoutError) as exc:
            last=exc
        if attempt < retries-1: time.sleep(1.5*(2**attempt))
    raise last

def parse_feed(raw,cfg,limit=15,feed_kind='channel'):
    root=ET.fromstring(raw); out=[]
    for e in root.findall(f'{{{ATOM}}}entry')[:limit]:
        vid=(e.findtext(f'{{{YT}}}videoId') or '').strip()
        title=(e.findtext(f'{{{ATOM}}}title') or '').strip()
        published=(e.findtext(f'{{{ATOM}}}published') or '').strip()
        updated=(e.findtext(f'{{{ATOM}}}updated') or '').strip()
        if not vid or not title: continue
        out.append({
          'channel_id':cfg['channel_id'],'channel_name':cfg['name'],'source_id':cfg['id'],'tier':cfg['tier'],
          'video_id':vid,'title':title,'url':f'https://www.youtube.com/watch?v={vid}',
          'shorts_url':f'https://www.youtube.com/shorts/{vid}' if feed_kind=='shorts' else '',
          'thumbnail_url':f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg','published_at':published,'updated_at':updated,
          'source_domain':'youtube.com','record_kind':'youtube_short' if feed_kind=='shorts' else 'youtube_video','feed_kind':feed_kind
        })
    return out

def fetch_channel(cfg,limit):
    attempts=[]
    for kind,url in endpoints(cfg['channel_id']):
        try:
            raw=request(url); found=parse_feed(raw,cfg,limit,kind)
            attempts.append({'feed_kind':kind,'url':url,'status':'PASS','count':len(found)})
            if found: return found,attempts,url,kind
        except Exception as exc:
            attempts.append({'feed_kind':kind,'url':url,'status':'ERROR','error':f'{type(exc).__name__}: {exc}'})
    return [],attempts,'',''

def collect(limit_per_channel=15):
    cfg=json.loads(CONFIG.read_text(encoding='utf-8')); records=[]; errors=[]; status=[]
    for ch in cfg['channels']:
        found,attempts,feed_url,feed_kind=fetch_channel(ch,limit_per_channel)
        records.extend(found)
        if found:
            status.append({'source_id':ch['id'],'status':'PASS','count':len(found),'feed_url':feed_url,'feed_kind':feed_kind,'attempts':attempts})
        else:
            errors.append({'source_id':ch['id'],'error':'all YouTube feed variants failed','attempts':attempts})
            status.append({'source_id':ch['id'],'status':'ERROR','count':0,'attempts':attempts})
    seen=set(); dedup=[]
    for r in records:
        if r['video_id'] in seen: continue
        seen.add(r['video_id']); dedup.append(r)
    healthy=sum(1 for x in status if x['status']=='PASS')
    health='HEALTHY' if not errors else ('DEGRADED' if healthy else 'UNAVAILABLE')
    return {'schema_version':'youtube-signals-candidates-v3','generated_at':now().isoformat(),'candidate_count':len(dedup),'error_count':len(errors),'healthy_source_count':healthy,'source_health':health,'source_status':status,'errors':errors,'candidates':dedup}

def select(data):
    cfg=json.loads(CONFIG.read_text(encoding='utf-8')); asof=parse_dt(data.get('generated_at')) or now(); ranked=[]; rejected=Counter()
    for c in data.get('candidates',[]):
        d=parse_dt(c.get('published_at'))
        if not d: rejected['missing_date']+=1; continue
        age=(asof-d).total_seconds()/86400
        if age < -1: rejected['future_date']+=1; continue
        if age > cfg['max_age_days']: rejected['stale']+=1; continue
        freshness=max(0,cfg['max_age_days']-max(0,age)); trust=max(0,4-int(c.get('tier',4)))
        ranked.append((freshness*10+trust,d,c))
    ranked.sort(key=lambda x:(x[0],x[1]),reverse=True)
    chosen=[]; per=Counter()
    for score,d,c in ranked:
        sid=c['source_id']
        if per[sid]>=cfg['max_per_channel']: continue
        item=dict(c); item['selection_score']=round(score,2); chosen.append(item); per[sid]+=1
        if len(chosen)>=cfg['target']: break
    status='PASS' if len(chosen)>=cfg['target'] and len(per)>=cfg['minimum_unique_channels'] else 'FAIL'
    return {'schema_version':'youtube-signals-selection-v3','generated_at':now().isoformat(),'as_of':asof.isoformat(),'coverage_status':status,'source_health':data.get('source_health','UNKNOWN'),'source_error_count':data.get('error_count',0),'selected_count':len(chosen),'unique_channels':len(per),'channel_counts':dict(per),'reject_counts':dict(rejected),'selected':chosen}

def self_test():
    raw=b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>abc123</yt:videoId><title>Example video</title><published>2026-09-02T00:00:00+00:00</published><updated>2026-09-02T00:01:00+00:00</updated></entry></feed>'''
    cfg={'channel_id':'UCX','name':'Example','id':'example','tier':2}
    got=parse_feed(raw,cfg,feed_kind='shorts'); assert got[0]['url']=='https://www.youtube.com/watch?v=abc123'; assert got[0]['shorts_url'].endswith('/abc123')
    eps=endpoints('UCABC'); assert 'playlist_id=UUABC' in eps[1][1] and 'playlist_id=UUSHABC' in eps[2][1]
    conf=json.loads(CONFIG.read_text(encoding='utf-8')); assert len(conf['channels'])>=4
    print('PASS: youtube signals collector self-test')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--limit-per-channel',type=int,default=15); ap.add_argument('--output',default='artifacts/youtube-signals-live.json'); ap.add_argument('--selected-output',default='artifacts/youtube-signals-selected.json')
    a=ap.parse_args()
    if a.self_test: self_test(); return 0
    data=collect(a.limit_per_channel); sel=select(data)
    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    s=Path(a.selected_output); s.write_text(json.dumps(sel,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"YOUTUBE candidates={data['candidate_count']} errors={data['error_count']} health={data['source_health']} selected={sel['selected_count']} channels={sel['unique_channels']} coverage={sel['coverage_status']}")
    for x in data['source_status']: print(' ',{k:v for k,v in x.items() if k!='attempts'})
    return 0 if sel['coverage_status']=='PASS' else 2

if __name__=='__main__': sys.exit(main())
