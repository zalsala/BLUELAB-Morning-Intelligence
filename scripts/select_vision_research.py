#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "vision-research-policy.json"

EVIDENCE_SCORE = {
    "META-ANALYSIS": 24,
    "SYSTEMATIC REVIEW": 22,
    "RCT": 20,
    "GUIDELINE": 18,
    "OBSERVATIONAL": 13,
    "CLINICAL TRIAL": 12,
    "REVIEW": 10,
    "PREPRINT": 7,
    "RESEARCH / ISSUE": 5,
}


def norm_title(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", (value or "").lower()).strip()


def parse_date(value: str):
    if not value:
        return None
    m = re.search(r"(20\d{2})[- /]?([01]?\d)?[- /]?([0-3]?\d)?", str(value))
    if not m:
        return None
    y = int(m.group(1)); mo = int(m.group(2) or 1); d = int(m.group(3) or 1)
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def domain(url: str) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def quality_score(item: dict, today: dt.date) -> int:
    score = EVIDENCE_SCORE.get(item.get("evidence_type"), 5)
    pd = parse_date(item.get("publication_date", ""))
    if pd:
        age = max(0, (today - pd).days)
        score += 20 if age <= 3 else 16 if age <= 7 else 10 if age <= 14 else 5 if age <= 30 else 0
    if item.get("doi"): score += 8
    if item.get("pmid"): score += 7
    if item.get("nct_id"): score += 5
    if item.get("abstract"): score += 7
    if item.get("journal"): score += 5
    if item.get("authors"): score += 3
    if item.get("url") and domain(item.get("url")): score += 4
    if item.get("collector_source") in {"pubmed","europe-pmc","crossref","clinicaltrials"}: score += 3
    return score


def select(items: list[dict], target: int, max_topic_share: float, today: dt.date):
    enriched=[]
    seen=set()
    for item in items:
        key = item.get("doi") or item.get("pmid") or item.get("nct_id") or norm_title(item.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        x=dict(item)
        x["selection_score"]=quality_score(x,today)
        enriched.append(x)
    enriched.sort(key=lambda x:(x["selection_score"], x.get("publication_date", "")), reverse=True)

    max_per_topic=max(1, int(target*max_topic_share))
    chosen=[]; topic_counts=Counter(); source_counts=Counter()
    # Pass 1: guarantee broad topical coverage when candidates exist.
    topic_best={}
    for x in enriched:
        topic_best.setdefault(x.get("topic_id") or "unknown", x)
    for x in sorted(topic_best.values(), key=lambda z:z["selection_score"], reverse=True):
        if len(chosen)>=target: break
        chosen.append(x); topic_counts[x.get("topic_id") or "unknown"]+=1; source_counts[x.get("collector_source") or "unknown"]+=1
    chosen_keys={x.get("doi") or x.get("pmid") or x.get("nct_id") or norm_title(x.get("title", "")) for x in chosen}

    # Pass 2: highest quality while enforcing topic concentration ceiling.
    for x in enriched:
        if len(chosen)>=target: break
        key=x.get("doi") or x.get("pmid") or x.get("nct_id") or norm_title(x.get("title", ""))
        if key in chosen_keys: continue
        topic=x.get("topic_id") or "unknown"
        if topic_counts[topic]>=max_per_topic: continue
        chosen.append(x); chosen_keys.add(key); topic_counts[topic]+=1; source_counts[x.get("collector_source") or "unknown"]+=1

    return chosen, topic_counts, source_counts


def self_test():
    today=dt.date(2026,9,2)
    rows=[]
    for i,topic in enumerate(["myopia","binocular","contact_cornea","ophthalmology","vision_science","optometry"]*3):
        rows.append({"title":f"paper {i}","topic_id":topic,"publication_date":"2026-09-01","evidence_type":"RCT" if i%2==0 else "OBSERVATIONAL","doi":f"10.1/{i}","abstract":"x","journal":"J","authors":["A"],"url":"https://doi.org/x","collector_source":"crossref"})
    chosen,tc,_=select(rows,10,.4,today)
    assert len(chosen)==10
    assert len(tc)>=6
    assert max(tc.values())<=4
    assert chosen[0]["selection_score"]>=chosen[-1]["selection_score"]
    print("PASS: vision research selector self-test")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--input",default="artifacts/vision-research-candidates.json")
    ap.add_argument("--output",default="artifacts/vision-research-selected.json")
    ap.add_argument("--target",type=int)
    args=ap.parse_args()
    if args.self_test:
        self_test(); return
    policy=json.loads(POLICY.read_text(encoding="utf-8"))
    payload=json.loads((ROOT/args.input).read_text(encoding="utf-8"))
    items=payload.get("candidates",[])
    target=args.target or int(policy.get("target_items",10))
    chosen,tc,sc=select(items,target,float(policy.get("max_single_topic_share",.4)),dt.date.today())
    out={
        "schema_version":"vision-research-selected-v1",
        "generated_at":dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "candidate_count":len(items),
        "selected_count":len(chosen),
        "target_count":target,
        "coverage_status":"PASS" if len(chosen)>=target else "LIMITED",
        "topic_counts":dict(tc),
        "collector_source_counts":dict(sc),
        "provider_errors":payload.get("errors",[]),
        "selected":chosen,
    }
    p=ROOT/args.output; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"WROTE {p}: selected {len(chosen)}/{target} from {len(items)} candidates; topics={dict(tc)}")
    if len(chosen)<target:
        raise SystemExit(2)

if __name__=="__main__":
    main()
