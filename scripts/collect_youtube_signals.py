#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, sys, urllib.request, xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'config'/'youtube-signals.json'
UA='BLUELAB-Morning-Intelligence/1.0 (+https://github.com/zalsala/BLUELAB-Morning-Intelligence)'
TIMEOUT=20
ATOM='http://www.w3.org/2005/Atom'
YT='http://www.youtube.com/xml/schemas/2015'
MEDIA='http://search.yahoo.com/mrss/'

def now(): return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
def parse_dt(v):
    try: return dt.datetime.fromisoformat((v or '').replace('Z','+00:00')).astimezone(dt.timezone.utc)
    except Exception: return None

def fetch(channel_id):
    url=f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/atom+xml, application/xml;q=0.9, */*;q=0.5'})
    with urllib.request.urlopen(req,timeout=TIMEOUT) as r: return r.read(),url

def parse_feed(raw,cfg,limit=15):
    root=ET.fromstring(raw); out=[]
    for e in root.findall(f'{{{ATOM}}}entry')[:limit]:
        vid=(e.findtext(f'{{{YT}}}videoId') or '').strip()
        title=(e.findtext(f'{{{ATOM}}}title') or '').strip()
        published=(e.findtext(f'{{{ATOM}}}published') or '').strip()
        updated=(e.findtext(f'{{{ATOM}}}updated') or '').strip()
        if not vid or not title: continue
        thumb=f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg'
        out.append({
          'channel_id':cfg['channel_id'],'channel_name':cfg['name'],'source_id':cfg['id'],'tier':cfg['tier'],
          'video_id':vid,'title':title,'url':f'https://www.youtube.com/watch?v={vid}','thumbnail_url':thumb,
          'published_at':published,'updated_at':updated,'source_domain':'youtube.com','record_kind':'youtube_video'
        })
    return out

def collect(limit_per_channel=15):
    cfg=json.loads(CONFIG.read_text(encoding='utf-8')); records=[]; errors=[]; status=[]
    for ch in cfg['channels']:
        try:
            raw,feed_url=fetch(ch['channel_id']); found=parse_feed(raw,ch,limit_per_channel); records.extend(found)
            status.append({'source_id':ch['id'],'status':'PASS','count':len(found),'feed_url':feed_url})
        except Exception as exc:
            errors.append({'source_id':ch['id'],'error':f'{type(exc).__name__}: {exc}'})
            status.append({'source_id':ch['id'],'status':'ERROR','count':0})
    seen=set(); dedup=[]
    for r in records:
        if r['video_id'] in seen: continue
        seen.add(r['video_id']); dedup.append(r)
    return {'schema_version':'youtube-signals-candidates-v1','generated_at':now().isoformat(),'candidate_count':len(dedup),'error_count':len(errors),'source_status':status,'errors':errors,'candidates':dedup}

def select(data):
    cfg=json.loads(CONFIG.read_text(encoding='utf-8')); asof=parse_dt(data.get('generated_at')) or now(); ranked=[]; rejected=Counter()
    for c in data.get('candidates',[]):
        d=parse_dt(c.get('published_at'))
        if not d: rejected['missing_date']+=1; continue
        age=(asof-d).total_seconds()/86400
        if age < -1: rejected['future_date']+=1; continue
        if age > cfg['max_age_days']: rejected['stale']+=1; continue
        freshness=max(0,cfg['max_age_days']-max(0,age)); trust=max(0,4-int(c.get('tier',4)))
        score=freshness*10+trust
        ranked.append((score,d,c))
    ranked.sort(key=lambda x:(x[0],x[1]),reverse=True)
    chosen=[]; per=Counter()
    for score,d,c in ranked:
        sid=c['source_id']
        if per[sid]>=cfg['max_per_channel']: continue
        item=dict(c); item['selection_score']=round(score,2); chosen.append(item); per[sid]+=1
        if len(chosen)>=cfg['target']: break
    status='PASS' if len(chosen)>=cfg['target'] and len(per)>=cfg['minimum_unique_channels'] else 'FAIL'
    return {'schema_version':'youtube-signals-selection-v1','generated_at':now().isoformat(),'as_of':asof.isoformat(),'coverage_status':status,'selected_count':len(chosen),'unique_channels':len(per),'channel_counts':dict(per),'reject_counts':dict(rejected),'selected':chosen}

def self_test():
    raw=b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>abc123</yt:videoId><title>Example video</title><published>2026-09-02T00:00:00+00:00</published><updated>2026-09-02T00:01:00+00:00</updated></entry></feed>'''
    cfg={'channel_id':'UCX','name':'Example','id':'example','tier':2}
    got=parse_feed(raw,cfg); assert got[0]['url']=='https://www.youtube.com/watch?v=abc123'; assert got[0]['thumbnail_url'].endswith('/abc123/hqdefault.jpg')
    conf=json.loads(CONFIG.read_text(encoding='utf-8')); assert len(conf['channels'])>=4
    print('PASS: youtube signals collector self-test')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--limit-per-channel',type=int,default=15); ap.add_argument('--output',default='artifacts/youtube-signals-live.json'); ap.add_argument('--selected-output',default='artifacts/youtube-signals-selected.json')
    a=ap.parse_args()
    if a.self_test: self_test(); return 0
    data=collect(a.limit_per_channel); sel=select(data)
    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    s=Path(a.selected_output); s.write_text(json.dumps(sel,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"YOUTUBE candidates={data['candidate_count']} errors={data['error_count']} selected={sel['selected_count']} channels={sel['unique_channels']} coverage={sel['coverage_status']}")
    for x in data['source_status']: print(' ',x)
    return 0 if sel['coverage_status']=='PASS' and data['error_count']==0 else 2

if __name__=='__main__': sys.exit(main())
