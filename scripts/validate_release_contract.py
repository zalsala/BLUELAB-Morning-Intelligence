#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"public"/"data"
SOURCE_POLICY=ROOT/"config"/"source-policy.json"
EXPECTED_FILES=[f"stories-{i}.json" for i in range(1,6)]
PLACEHOLDER=re.compile(r"(^|\W)(undefined|null|tbd|todo|placeholder)(\W|$)",re.I)

def fail(errors,msg):
    errors.append(msg)

def valid_http_url(v):
    try:
        u=urlparse(v or "")
        return u.scheme in {"http","https"} and bool(u.netloc)
    except Exception:
        return False

def load():
    today=json.loads((DATA/"today.json").read_text(encoding="utf-8"))
    policy=json.loads(SOURCE_POLICY.read_text(encoding="utf-8"))
    files=today.get("story_files",[])
    stories=[]
    if files==EXPECTED_FILES:
        for name in files:
            p=DATA/name
            if p.exists():
                chunk=json.loads(p.read_text(encoding="utf-8"))
                if isinstance(chunk,list): stories.extend(chunk)
    return today,policy,files,stories

def audit(release=False):
    today,policy,files,stories=load()
    errors=[]
    if files!=EXPECTED_FILES: fail(errors,f"story_files must equal {EXPECTED_FILES}")
    if len(stories)<5: fail(errors,"story bundles contain fewer than 5 stories")
    titles=[s.get("title","").strip() for s in stories]
    if any(not t for t in titles): fail(errors,"one or more stories have blank title")
    dup=[t for t,n in Counter(titles).items() if t and n>1]
    if dup: fail(errors,f"duplicate story titles: {dup[:10]}")
    top5=today.get("top5_titles",[])
    if len(top5)!=5 or len(set(top5))!=5: fail(errors,"TOP5 must contain exactly five unique titles")
    missing=[t for t in top5 if t not in set(titles)]
    if missing: fail(errors,f"TOP5 titles missing from story bundles: {missing}")
    if today.get("top_issue_title") not in set(titles): fail(errors,"top_issue_title missing from story bundles")

    grouped=defaultdict(list)
    for s in stories: grouped[s.get("section","")].append(s)
    top5set=set(top5)
    chapter_counts={}
    for chapter in policy.get("chapters",{}):
        rendered=[s for s in grouped.get(chapter,[]) if s.get("title") not in top5set]
        chapter_counts[chapter]=len(rendered)
        if len(rendered)<10: fail(errors,f"{chapter}: rendered count {len(rendered)} < 10 after TOP5 exclusion")

    summary=today.get("final_three_line_summary",[])
    if not isinstance(summary,list) or len(summary)!=3 or any(not str(x).strip() for x in summary):
        fail(errors,"final_three_line_summary must contain exactly 3 nonblank lines")

    if release:
        trends=today.get("trends",[])
        if len(trends)!=20 or [x.get("rank") for x in trends] != list(range(1,21)):
            fail(errors,"release requires exactly 20 ranked Trends entries")
        weather=today.get("weather") or {}
        for key in ["location_label","current_temp","condition","high","low","precip_probability","humidity","wind","alert","life_note","tomorrow_summary","weather_source","weather_updated_at"]:
            if not str(weather.get(key,"")).strip(): fail(errors,f"weather missing: {key}")
        metrics=today.get("metrics",[])
        if not isinstance(metrics,list) or len(metrics)<5: fail(errors,"release requires at least 5 market metrics")
        videos=today.get("videos",[])
        if not isinstance(videos,list) or len(videos)<10:
            fail(errors,f"release requires at least 10 YouTube/Shorts video records; found {len(videos) if isinstance(videos,list) else 0}")
        else:
            for i,v in enumerate(videos,1):
                u=v.get("url") or v.get("video_url") or v.get("source_url")
                if not valid_http_url(u): fail(errors,f"video {i} missing valid URL")
        def walk(x,path="today"):
            if isinstance(x,dict):
                for k,v in x.items(): walk(v,f"{path}.{k}")
            elif isinstance(x,list):
                for i,v in enumerate(x): walk(v,f"{path}[{i}]")
            elif isinstance(x,str) and PLACEHOLDER.search(x):
                fail(errors,f"placeholder token in {path}: {x[:80]}")
        walk(today)

    mode="RELEASE" if release else "STRUCTURAL"
    print(f"CONTRACT_{mode} edition={today.get('meta',{}).get('edition','unknown')}")
    for ch,n in chapter_counts.items(): print(f"  {ch}: {n}")
    if errors:
        print("ERRORS:")
        for e in errors: print("  -",e)
        return 1
    print(f"PASS: contract {mode.lower()} gate")
    return 0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--release",action="store_true")
    args=ap.parse_args()
    return audit(args.release)

if __name__=="__main__": sys.exit(main())
