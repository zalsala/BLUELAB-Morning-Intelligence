#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

INTERNATIONAL_CHAPTER='국제 · 외교 · 안보'
SCIENCE_CHAPTER='과학'
NON_FACTUAL_SEGMENTS={'opinion','opinions','comment','comments','commentisfree','editorial','columns','column','press-review','press_reviews','analysis','fault-lines'}
PUBLIC_SAFETY_INCIDENT_TERMS=('blast','explosion','bomb','detonated')
SCIENCE_BRIEFING_TERMS=('media briefing','press briefing')
SCIENCE_CONTENT_FILLER_TERMS=('podcast','podcast series')

def classify_url(url: str) -> str:
    try:
        path=urlparse(url or '').path
        segments={x.lower() for x in path.split('/') if x}
        if segments & NON_FACTUAL_SEGMENTS:
            return 'non_factual_path'
    except Exception:
        return 'bad_url'
    return ''

def classify_candidate(c: dict) -> str:
    reason=classify_url(c.get('canonical_url') or c.get('url',''))
    if reason:return reason
    title=(c.get('title') or '').lower()
    summary=(c.get('summary') or '').lower()
    text=title+' '+summary
    chapter=c.get('chapter')
    if chapter==INTERNATIONAL_CHAPTER and 'police station' in text and any(x in text for x in PUBLIC_SAFETY_INCIDENT_TERMS):
        return 'public_safety_incident'
    if chapter==SCIENCE_CHAPTER:
        if any(x in title for x in SCIENCE_BRIEFING_TERMS):
            return 'science_briefing'
        if any(x in title for x in SCIENCE_CONTENT_FILLER_TERMS):
            return 'science_content_filler'
        source=(c.get('source') or '').lower()
        roman_launch=('roman' in title and any(x in title for x in ('launch','lifts off','lift-off','lift off')))
        if source.startswith('esa') and roman_launch:
            return 'prefer_primary_source'
    return ''

def filter_data(data: dict) -> dict:
    kept=[]; rejected=[]; reasons=Counter(); chapters=Counter()
    for c in data.get('candidates',[]):
        reason=classify_candidate(c)
        if reason:
            reasons[reason]+=1
            rejected.append({'chapter':c.get('chapter'),'title':c.get('title'),'url':c.get('url'),'reason':reason})
            continue
        kept.append(c); chapters[c.get('chapter','')]+=1
    out=dict(data)
    out['schema_version']='priority-news-factual-candidates-v6'
    out['unfiltered_candidate_count']=len(data.get('candidates',[]))
    out['candidate_count']=len(kept)
    out['factual_prefilter']={
        'rejected_count':len(rejected),
        'reason_counts':dict(reasons),
        'chapter_counts':dict(chapters),
        'rejected':rejected,
    }
    out['candidates']=kept
    return out

def self_test():
    data={'candidates':[
      {'chapter':INTERNATIONAL_CHAPTER,'title':'Fact','url':'https://example.com/news/2026/fact'},
      {'chapter':INTERNATIONAL_CHAPTER,'title':'Opinion','url':'https://example.com/opinions/2026/view'},
      {'chapter':'경제 · 시장','title':'Column','url':'https://example.com/columns/market-view'},
      {'chapter':INTERNATIONAL_CHAPTER,'title':'Press review','url':'https://example.com/tv-shows/press-review/2026/story'},
      {'chapter':INTERNATIONAL_CHAPTER,'title':'Documentary','url':'https://example.com/video/fault-lines/2026/story'},
      {'chapter':INTERNATIONAL_CHAPTER,'title':"Blast near police station on Colombia's border leaves casualties",'summary':'A car packed with explosives detonated outside a police station','url':'https://example.com/world/incident'},
      {'chapter':SCIENCE_CHAPTER,'title':"Media briefing: BepiColombo's next milestone towards Mercury",'source':'ESA Space Science','url':'https://esa.example/briefing'},
      {'chapter':SCIENCE_CHAPTER,'title':'Expedition Sound podcast series','source':'ESA Space Science','url':'https://esa.example/podcast'},
      {'chapter':SCIENCE_CHAPTER,'title':'Roman lifts off on a mission to survey the infrared sky','source':'ESA Space Science','url':'https://esa.example/roman'},
      {'chapter':SCIENCE_CHAPTER,'title':'NASA’s Nancy Grace Roman Space Telescope Launches','source':'NASA','url':'https://nasa.example/roman'}
    ]}
    out=filter_data(data)
    assert out['candidate_count']==2,out
    assert out['factual_prefilter']['rejected_count']==8,out
    assert out['factual_prefilter']['reason_counts']['non_factual_path']==4,out
    assert out['factual_prefilter']['reason_counts']['public_safety_incident']==1,out
    assert out['factual_prefilter']['reason_counts']['science_briefing']==1,out
    assert out['factual_prefilter']['reason_counts']['science_content_filler']==1,out
    assert out['factual_prefilter']['reason_counts']['prefer_primary_source']==1,out
    kept_titles={x['title'] for x in out['candidates']}
    assert 'NASA’s Nancy Grace Roman Space Telescope Launches' in kept_titles
    print('PASS: factual priority candidate prefilter self-test')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input'); ap.add_argument('--output'); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:self_test();return 0
    if not a.input or not a.output:ap.error('--input and --output required')
    data=json.loads(Path(a.input).read_text(encoding='utf-8')); out=filter_data(data)
    p=Path(a.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"FACTUAL_PREFILTER kept={out['candidate_count']} rejected={out['factual_prefilter']['rejected_count']} reasons={out['factual_prefilter']['reason_counts']}")
    for x in out['factual_prefilter']['rejected'][:20]:print(' REJECT',x)
    return 0
if __name__=='__main__':sys.exit(main())
