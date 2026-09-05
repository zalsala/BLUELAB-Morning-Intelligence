#!/usr/bin/env python3
from __future__ import annotations

import argparse,json,re,sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"public"/"data"; EXPECTED_FILES=[f"stories-{i}.json" for i in range(1,6)]; PLACEHOLDER=re.compile(r"(^|\W)(undefined|null|tbd|todo|placeholder)(\W|$)",re.I); KST=ZoneInfo("Asia/Seoul"); VISION_ID="vision-research-watch"

def valid_http_url(value:str)->bool:
    try:
        p=urlparse(value or ""); return p.scheme in {"http","https"} and bool(p.netloc)
    except Exception:return False

def audit(release:bool=False,expected_date:str|None=None)->int:
    today=json.loads((DATA/"today.json").read_text(encoding="utf-8")); manifest=json.loads((DATA/"publication_manifest.json").read_text(encoding="utf-8")); errors=[]
    metadata=today.get("metadata",{}); date=metadata.get("date"); expected=expected_date or datetime.now(KST).strftime("%Y-%m-%d")
    if date!=expected: errors.append(f"edition date mismatch: {date} != {expected}")

    chapters=today.get("chapters",[]); general=[c for c in chapters if c.get("id")!=VISION_ID]; vision=[c for c in chapters if c.get("id")==VISION_ID]
    if len(general)!=14: errors.append(f"general chapter count={len(general)} != 14")
    if len(vision)!=1: errors.append(f"VISION RESEARCH WATCH chapter count={len(vision)} != 1")
    articles=[]
    for c in general:
        ca=c.get("articles",[])
        if len(ca)<10: errors.append(f"{c.get('name')}: rendered items={len(ca)} < 10")
        articles.extend(ca)
    if len(articles)!=140: errors.append(f"general rendered article total={len(articles)} != 140")
    vrows=vision[0].get("articles",[]) if vision else []
    if len(vrows)!=10: errors.append(f"VISION RESEARCH WATCH rendered items={len(vrows)} != 10")
    if vision and len(chapters)!=15: errors.append(f"total rendered chapter count={len(chapters)} != 15")

    all_urls=[a.get("link","") for a in articles+vrows]
    if len(all_urls)!=len(set(all_urls)): errors.append("cross-chapter duplicate article URLs remain")
    for idx,url in enumerate(all_urls,1):
        if not valid_http_url(url): errors.append(f"article {idx} missing valid exact URL")
        elif urlparse(url).netloc.lower().endswith("news.google.com"): errors.append(f"article {idx} still uses Google News relay URL")

    for a in vrows:
        rw=a.get("research_watch") or {}
        for key in ("evidence_type","study_design","clinical_meaning_ko","limitations_conflicts_ko","exact_source_url"):
            if not rw.get(key): errors.append(f"VISION RESEARCH WATCH missing {key}: {a.get('title','')}")

    top5=today.get("top_5_highlights",[])
    if len(top5)!=5 or len({x.get('id') for x in top5})!=5: errors.append("TOP5 must contain exactly five unique items")

    story_files=metadata.get("story_files",[])
    if story_files!=EXPECTED_FILES: errors.append(f"metadata.story_files must equal {EXPECTED_FILES}")
    else:
        bundled=[]
        for name in story_files:
            chunk=json.loads((DATA/name).read_text(encoding="utf-8"))
            if not isinstance(chunk,list): errors.append(f"{name} must contain a JSON list")
            else: bundled.extend(chunk)
        if len(bundled)!=140: errors.append(f"story bundle total={len(bundled)} != 140")
        if {x.get('url') for x in bundled}!={a.get('link') for a in articles}: errors.append("five story bundles do not exactly match the 140 general article URLs")

    watch_file=DATA/"vision-research-watch.json"
    if not watch_file.exists(): errors.append("vision-research-watch.json missing")
    else:
        watch=json.loads(watch_file.read_text(encoding="utf-8"))
        if watch.get("selected_count")!=10 or watch.get("coverage_status")!="PASS": errors.append("vision-research-watch.json is not PASS/10")

    trends=today.get("trending_keywords",[]); trends_source=metadata.get("trends_source")
    if len(trends)==20:
        if trends_source!="Google Trends KR official RSS": errors.append("20 Trends entries require official Google Trends KR RSS provenance")
    elif len(trends)==0:
        if trends_source!="WITHHELD_INSUFFICIENT_RELIABLE_TERMS": errors.append("withheld Trends requires explicit insufficiency status")
    else: errors.append(f"Trends must be exactly 20 reliable entries or 0 withheld; found {len(trends)}")

    weather=today.get("weather") or {}
    for key in ["location","temp_current","temp_min","temp_max","condition","precipitation_prob"]:
        if weather.get(key) is None or weather.get(key)=="": errors.append(f"weather missing: {key}")
    if not weather.get("source"): errors.append("weather missing explicit source/source-level label")

    market=today.get("market") or {}
    for key in ["kospi","usd_krw"]:
        if market.get(key) is None: errors.append(f"market missing: {key}")
    videos=today.get("youtube_hot_issues",[])
    if len(videos)<10: errors.append(f"YouTube/Shorts count={len(videos)} < 10")
    if len({v.get('channel') for v in videos if v.get('channel')})<4: errors.append("YouTube/Shorts unique channels < 4")
    for idx,v in enumerate(videos,1):
        u=v.get("url") or v.get("video_url") or v.get("source_url")
        if not valid_http_url(u): errors.append(f"video {idx} missing valid URL")
    if len(today.get("next_signals",[]))<3: errors.append("NEXT SIGNALS must contain at least 3 items")
    if len(today.get("three_line_summary",[]))!=3: errors.append("three_line_summary must contain exactly 3 lines")

    if manifest.get("edition_date")!=expected: errors.append(f"manifest edition mismatch: {manifest.get('edition_date')} != {expected}")
    if manifest.get("canonical_status")!="CANONICAL_PASS": errors.append(f"manifest canonical_status={manifest.get('canonical_status')} != CANONICAL_PASS")
    if today.get("publication_manifest_fingerprint")!=manifest.get("manifest_sha256"): errors.append("today.json publication manifest fingerprint mismatch")

    if release:
        def walk(value,path="today"):
            if isinstance(value,dict):
                for k,c in value.items(): walk(c,f"{path}.{k}")
            elif isinstance(value,list):
                for i,c in enumerate(value): walk(c,f"{path}[{i}]")
            elif isinstance(value,str) and PLACEHOLDER.search(value): errors.append(f"placeholder token in {path}: {value[:80]}")
        walk(today)
    mode="RELEASE" if release else "STRUCTURAL"; print(f"CONTRACT_{mode} edition={date}")
    if errors:
        print("ERRORS:"); [print("  -",e) for e in errors]; return 1
    print(f"PASS: contract {mode.lower()} gate"); return 0

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--release",action="store_true"); p.add_argument("--expected-date",default=None); p.add_argument("--expected-today-kst",action="store_true"); a=p.parse_args(); expected=datetime.now(KST).strftime("%Y-%m-%d") if a.expected_today_kst else a.expected_date
    if a.expected_today_kst and a.expected_date and a.expected_date!=expected: print(f"ERROR: explicit expected-date {a.expected_date} conflicts with KST today {expected}"); return 2
    return audit(a.release,expected)
if __name__=="__main__": sys.exit(main())
