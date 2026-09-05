"""Strict production QA for BLUELAB Morning Intelligence."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from pipeline.schema import FACT_CHECK_STATES
from pipeline.top5_ranker import is_top5_title_eligible

EXPECTED_GENERAL_CHAPTERS=14
EXPECTED_ARTICLES_PER_CHAPTER=10
EXPECTED_GENERAL_ARTICLES=140
EXPECTED_TOP5_COUNT=5
VISION_ID="vision-research-watch"
ALLOWED_BODY_VALIDATION_STATES={"VALIDATED","EVENT_MISMATCH","NO_QUALIFIED_BODY","HTTP_403","HTTP_404","TIMEOUT"}


def run_qa_gate(json_path:str="public/data/today.json")->bool:
    print("="*75); print(" [QA GATE] BLUELAB Morning Intelligence 엄격 품질 검사 시작"); print("="*75)
    failures:List[str]=[]
    if not os.path.exists(json_path): print(f" [FAIL] missing file: {json_path}"); return False
    try:
        with open(json_path,"r",encoding="utf-8") as f: data=json.load(f)
    except Exception as exc: print(f" [FAIL] JSON parse error: {exc}"); return False

    canonical_v11=data.get("metadata",{}).get("version")=="1.1.0"
    chapters=data.get("chapters",[])
    vision=[ch for ch in chapters if ch.get("id")==VISION_ID]
    general=[ch for ch in chapters if ch.get("id")!=VISION_ID]
    vision_enabled=len(vision)>0

    if len(general)!=EXPECTED_GENERAL_CHAPTERS: failures.append(f"general chapter count={len(general)} != 14")
    if vision_enabled and len(vision)!=1: failures.append(f"VISION RESEARCH WATCH chapter count={len(vision)} != 1")
    if vision_enabled and len(chapters)!=15: failures.append(f"rendered chapter count={len(chapters)} != 15")
    if not vision_enabled and len(chapters)!=14: failures.append(f"chapter count={len(chapters)} != 14")

    general_articles=[]
    for ch in general:
        arts=ch.get("articles",[]); general_articles.extend(arts)
        if len(arts)!=EXPECTED_ARTICLES_PER_CHAPTER: failures.append(f"{ch.get('name')}: article count={len(arts)} != 10")
    if len(general_articles)!=EXPECTED_GENERAL_ARTICLES: failures.append(f"general articles={len(general_articles)} != 140")

    vision_articles=vision[0].get("articles",[]) if vision_enabled else []
    if vision_enabled and len(vision_articles)!=10: failures.append(f"VISION RESEARCH WATCH articles={len(vision_articles)} != 10")
    all_articles=general_articles+vision_articles
    expected_total=150 if vision_enabled else 140
    if len(all_articles)!=expected_total: failures.append(f"total rendered articles={len(all_articles)} != {expected_total}")

    ids=[a.get("id","") for a in all_articles]; urls=[a.get("link","") for a in all_articles]; titles=[a.get("title","") for a in all_articles]
    for label,values in (("id",ids),("url",urls),("title",titles)):
        if any(not x for x in values): failures.append(f"missing article {label}")
        if len(values)!=len(set(values)): failures.append(f"duplicate article {label}")
    relays=[u for u in urls if urlparse(u).netloc.lower().endswith("news.google.com")]
    if relays: failures.append(f"exact article URL gate: {len(relays)} Google News relay URLs remain")

    verified_image_hashes=[]
    for art in all_articles:
        ed=art.get("editorial",{})
        if len((ed.get("fact") or "").strip())<10: failures.append(f"editorial fact incomplete: {art.get('title','')[:30]}")
        if len((ed.get("background") or "").strip())<10: failures.append(f"editorial background incomplete: {art.get('title','')[:30]}")
        if len((ed.get("why_it_matters") or "").strip())<10: failures.append(f"editorial why incomplete: {art.get('title','')[:30]}")
        if len(ed.get("checkpoints") or [])<2: failures.append(f"editorial checkpoints incomplete: {art.get('title','')[:30]}")
        fc=art.get("fact_check")
        if not isinstance(fc,dict): failures.append(f"missing fact_check data: {art.get('title','')[:30]}")
        else:
            st=fc.get("status")
            if st not in FACT_CHECK_STATES: failures.append(f"invalid fact_check status {st!r}: {art.get('title','')[:30]}")
            if canonical_v11:
                bv=fc.get("body_validation")
                if not isinstance(bv,dict): failures.append(f"missing body_validation data: {art.get('title','')[:30]}")
                elif bv.get("status") not in ALLOWED_BODY_VALIDATION_STATES: failures.append(f"invalid body_validation status {bv.get('status')!r}: {art.get('title','')[:30]}")
        img=art.get("image")
        if not isinstance(img,dict): failures.append(f"missing image provenance structure: {art.get('title','')[:30]}")
        else:
            ist=img.get("status")
            if ist not in ("VERIFIED_PROVENANCE","EXPLICIT_NULL"): failures.append(f"invalid image provenance status {ist!r}: {art.get('title','')[:30]}")
            if ist=="EXPLICIT_NULL" and img.get("url") is not None: failures.append(f"EXPLICIT_NULL must have url=None: {art.get('title','')[:30]}")
            if ist=="VERIFIED_PROVENANCE":
                if not img.get("url"): failures.append(f"VERIFIED_PROVENANCE missing url: {art.get('title','')[:30]}")
                if canonical_v11:
                    if not img.get("content_hash"): failures.append(f"VERIFIED_PROVENANCE missing content_hash: {art.get('title','')[:30]}")
                    else: verified_image_hashes.append(img.get("content_hash"))
                    if not img.get("declaration_method"): failures.append(f"VERIFIED_PROVENANCE missing declaration_method: {art.get('title','')[:30]}")
                    if not img.get("source_domain") or not img.get("article_domain"): failures.append(f"VERIFIED_PROVENANCE missing domain provenance: {art.get('title','')[:30]}")
    if canonical_v11 and len(verified_image_hashes)!=len(set(verified_image_hashes)): failures.append("duplicate VERIFIED_PROVENANCE image content_hash remains")

    if vision_enabled:
        domains=set()
        for art in vision_articles:
            rw=art.get("research_watch") or {}
            for key in ("evidence_type","study_design","clinical_meaning_ko","limitations_conflicts_ko","exact_source_url"):
                if not rw.get(key): failures.append(f"VISION RESEARCH WATCH missing {key}: {art.get('title','')}")
            u=rw.get("exact_source_url") or art.get("link",""); host=(urlparse(u).hostname or "").lower().removeprefix("www.")
            if host: domains.add(host)
        if len(domains)<5: failures.append(f"VISION RESEARCH WATCH source domains={len(domains)} < 5")

    weather=data.get("weather") or {}
    if "인천 서구 검단" not in weather.get("location","") or "temp_current" not in weather: failures.append("Geomdan weather missing/incomplete")
    # The enhanced production contract (Vision watch present) requires explicit
    # weather provenance. Legacy unit fixtures intentionally omit this field.
    if vision_enabled and not weather.get("source"): failures.append("Geomdan weather source level/source missing")

    top5=data.get("top_5_highlights",[])
    if len(top5)!=EXPECTED_TOP5_COUNT: failures.append("TOP5 must contain exactly 5 items")
    top5_ids=[a.get("id","") for a in top5]; top5_urls=[a.get("link","") for a in top5]
    if any(not x for x in top5_ids) or len(top5_ids)!=len(set(top5_ids)): failures.append("TOP5 ids must be present and unique")
    general_ids={a.get("id","") for a in general_articles}; general_urls={a.get("link","") for a in general_articles}
    if any(x not in general_ids for x in top5_ids): failures.append("TOP5 contains item not present in canonical 140 general-story snapshot")
    if any(x not in general_urls for x in top5_urls): failures.append("TOP5 contains URL not present in canonical 140 general-story snapshot")
    if any(urlparse(u).netloc.lower().endswith("news.google.com") for u in top5_urls): failures.append("TOP5 exact URL gate: Google News relay URL remains")
    if [a for a in top5 if not is_top5_title_eligible(a.get("title",""))]: failures.append("TOP5 factual-news gate: opinion/editorial item remains")
    if canonical_v11 and len(top5)==5 and len({a.get("chapter_id","") for a in top5})!=5: failures.append("TOP5 chapter diversity gate: expected 5 distinct chapters")

    market=data.get("market") or {}
    if not market or "kospi" not in market or "usd_krw" not in market: failures.append("financial market block missing/incomplete")
    next_signals=data.get("next_signals") or []
    if len(next_signals)<3: failures.append(f"NEXT SIGNALS count={len(next_signals)} < 3")
    trends=data.get("trending_keywords",[]); trends_source=data.get("metadata",{}).get("trends_source","")
    if len(trends) not in (0,20): failures.append(f"Google Trends count must be 0 or 20; found {len(trends)}")
    if len(trends)==0 and trends_source!="WITHHELD_INSUFFICIENT_RELIABLE_TERMS": failures.append("withheld Trends must carry explicit insufficiency status")
    if len(trends)==20 and trends_source!="Google Trends KR official RSS": failures.append("20 Trends terms must be sourced from official Google Trends KR RSS")
    if len(data.get("three_line_summary",[]))!=3: failures.append("final summary must contain exactly 3 lines")
    if len(data.get("youtube_hot_issues",[]))<10: failures.append("YouTube/Shorts must contain at least 10 verified records")
    if len({v.get("channel") for v in data.get("youtube_hot_issues",[]) if v.get("channel")})<4: failures.append("YouTube/Shorts must span at least 4 channels")
    if len(data.get("integrity_hash",""))<32: failures.append("integrity_hash missing/invalid")

    if failures:
        print(" [QA GATE REJECTED]")
        for i,f in enumerate(failures[:50],1): print(f"  {i}. {f}")
        return False
    print(" [QA GATE PASSED]")
    print(f"  general_chapters=14 general_articles=140 vision={len(vision_articles)} rendered={len(all_articles)} top5=5 youtube={len(data.get('youtube_hot_issues',[]))} trends={len(trends)} summary_lines=3 market=PASS signals={len(next_signals)}")
    return True

if __name__=="__main__":
    target=sys.argv[1] if len(sys.argv)>1 else "public/data/today.json"; raise SystemExit(0 if run_qa_gate(target) else 1)
