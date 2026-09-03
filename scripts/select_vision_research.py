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

# Topic labels from the acquisition query are discovery hints only.  A provider
# can return unrelated records, so final selection must independently prove
# ophthalmic/visual relevance from title + abstract.
TOPIC_TERMS = {
    "myopia": (
        "myopia", "myopic", "axial length", "spherical equivalent", "orthokeratology",
        "atropine", "defocus", "myopia control", "myopia progression",
    ),
    "binocular": (
        "binocular", "strabismus", "amblyopia", "vergence", "convergence", "divergence",
        "accommodation", "accommodative", "stereopsis", "stereoacuity", "heterophoria",
        "phoria", "diplopia", "ocular alignment", "fusional", "suppression",
    ),
    "contact_cornea": (
        "contact lens", "contact lenses", "cornea", "corneal", "keratitis", "keratoconus",
        "tear film", "dry eye", "ocular surface", "delefilcon", "senofilcon", "silicone hydrogel",
    ),
    "ophthalmology": (
        "retina", "retinal", "macula", "macular", "glaucoma", "cataract", "ophthalm",
        "optic nerve", "uveitis", "stargardt", "diabetic retinopathy", "retinal dystrophy",
        "age-related macular", "ocular", "eye disease",
    ),
    "vision_science": (
        "vision", "visual", "retina", "retinal", "ocular", "optical", "optics", "photoreceptor",
        "contrast sensitivity", "visual acuity", "visual field", "color vision", "colour vision",
        "eye movement", "oculomotor", "pupil", "pupillary",
    ),
    "optometry": (
        "optometr", "refraction", "refractive", "visual acuity", "vision screening", "eye exam",
        "ocular", "ophthalm", "contact lens", "binocular vision", "low vision", "spectacle",
    ),
}


def norm_title(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", (value or "").lower()).strip()


def parse_date(value: str):
    if not value:
        return None
    text = str(value)
    m = re.search(r"(20\d{2})[- /]?([01]?\d)?[- /]?([0-3]?\d)?", text)
    if not m:
        # Handle PubMed-style values such as "2026-Sep".
        y = re.search(r"\b(20\d{2})\b", text)
        if not y:
            return None
        month_names = {name.lower(): i for i, name in enumerate(
            ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}
        mm = 1
        lower = text.lower()
        for name, i in month_names.items():
            if name in lower:
                mm = i; break
        return dt.date(int(y.group(1)), mm, 1)
    y = int(m.group(1)); mo = int(m.group(2) or 1); d = int(m.group(3) or 1)
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def domain(url: str) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def topic_relevant(item: dict) -> bool:
    topic = item.get("topic_id") or ""
    terms = TOPIC_TERMS.get(topic, ())
    if not terms:
        return False
    text = " " + norm_title((item.get("title") or "") + " " + (item.get("abstract") or "")) + " "
    for term in terms:
        t = norm_title(term)
        if t and (" " + t + " ") in text:
            return True
    return False


def quality_score(item: dict, today: dt.date) -> int:
    score = EVIDENCE_SCORE.get(item.get("evidence_type"), 5)
    pd = parse_date(item.get("publication_date", ""))
    if pd:
        age = (today - pd).days
        if age < 0:
            return -10_000
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
    reject_counts=Counter()
    for item in items:
        key = item.get("doi") or item.get("pmid") or item.get("nct_id") or norm_title(item.get("title", ""))
        if not key or key in seen:
            reject_counts["duplicate_or_empty"] += 1
            continue
        seen.add(key)
        if not topic_relevant(item):
            reject_counts["topic_irrelevant"] += 1
            continue
        pd = parse_date(item.get("publication_date", ""))
        if pd and pd > today:
            reject_counts["future_publication"] += 1
            continue
        x=dict(item)
        x["selection_score"]=quality_score(x,today)
        enriched.append(x)
    enriched.sort(key=lambda x:(x["selection_score"], x.get("publication_date", "")), reverse=True)

    max_per_topic=max(1, int(target*max_topic_share))
    chosen=[]; topic_counts=Counter(); source_counts=Counter()
    topic_best={}
    for x in enriched:
        topic_best.setdefault(x.get("topic_id") or "unknown", x)
    for x in sorted(topic_best.values(), key=lambda z:z["selection_score"], reverse=True):
        if len(chosen)>=target: break
        chosen.append(x); topic_counts[x.get("topic_id") or "unknown"]+=1; source_counts[x.get("collector_source") or "unknown"]+=1
    chosen_keys={x.get("doi") or x.get("pmid") or x.get("nct_id") or norm_title(x.get("title", "")) for x in chosen}

    for x in enriched:
        if len(chosen)>=target: break
        key=x.get("doi") or x.get("pmid") or x.get("nct_id") or norm_title(x.get("title", ""))
        if key in chosen_keys: continue
        topic=x.get("topic_id") or "unknown"
        if topic_counts[topic]>=max_per_topic: continue
        chosen.append(x); chosen_keys.add(key); topic_counts[topic]+=1; source_counts[x.get("collector_source") or "unknown"]+=1

    return chosen, topic_counts, source_counts, reject_counts, len(enriched)


def self_test():
    today=dt.date(2026,9,3)
    good=[
        {"title":"Low-dose atropine for childhood myopia progression","abstract":"axial length","topic_id":"myopia","publication_date":"2026-09-02","evidence_type":"RCT","doi":"10.1/a","url":"https://doi.org/10.1/a","collector_source":"crossref"},
        {"title":"Vergence and accommodation in intermittent exotropia","abstract":"binocular vision","topic_id":"binocular","publication_date":"2026-09-02","evidence_type":"OBSERVATIONAL","doi":"10.1/b","url":"https://doi.org/10.1/b","collector_source":"crossref"},
        {"title":"Daily disposable toric contact lens comfort","abstract":"senofilcon contact lens","topic_id":"contact_cornea","publication_date":"2026-09-02","evidence_type":"RCT","doi":"10.1/c","url":"https://doi.org/10.1/c","collector_source":"crossref"},
        {"title":"ABCA4 retinal dystrophy gene therapy","abstract":"Stargardt retinal disease","topic_id":"ophthalmology","publication_date":"2026-09-02","evidence_type":"CLINICAL TRIAL","doi":"10.1/d","url":"https://doi.org/10.1/d","collector_source":"crossref"},
        {"title":"Visual acuity and contrast sensitivity after adaptation","abstract":"vision science","topic_id":"vision_science","publication_date":"2026-09-02","evidence_type":"RESEARCH / ISSUE","doi":"10.1/e","url":"https://doi.org/10.1/e","collector_source":"crossref"},
        {"title":"Optometry refraction screening outcomes","abstract":"eye exam","topic_id":"optometry","publication_date":"2026-09-02","evidence_type":"OBSERVATIONAL","doi":"10.1/f","url":"https://doi.org/10.1/f","collector_source":"crossref"},
    ]
    bad=[
        {"title":"Ecosystem services pricing in wetlands","abstract":"economics","topic_id":"vision_science","publication_date":"2026-09-02","doi":"10.1/x"},
        {"title":"Body armor 3D scanning","abstract":"female torso armor","topic_id":"binocular","publication_date":"2026-09-02","doi":"10.1/y"},
        {"title":"Future myopia trial","abstract":"myopia axial length","topic_id":"myopia","publication_date":"2027-01-01","doi":"10.1/z"},
    ]
    chosen,tc,_,rc,eligible=select(good+bad,10,.4,today)
    assert len(chosen)==6
    assert eligible==6
    assert len(tc)==6
    assert rc["topic_irrelevant"]==2
    assert rc["future_publication"]==1
    assert all(topic_relevant(x) for x in chosen)
    print("PASS: vision research selector relevance self-test")


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
    chosen,tc,sc,rc,eligible=select(items,target,float(policy.get("max_single_topic_share",.4)),dt.date.today())
    out={
        "schema_version":"vision-research-selected-v2",
        "generated_at":dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "candidate_count":len(items),
        "eligible_count":eligible,
        "selected_count":len(chosen),
        "target_count":target,
        "coverage_status":"PASS" if len(chosen)>=target else "LIMITED",
        "topic_counts":dict(tc),
        "collector_source_counts":dict(sc),
        "reject_counts":dict(rc),
        "provider_errors":payload.get("errors",[]),
        "selected":chosen,
    }
    p=ROOT/args.output; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"WROTE {p}: selected {len(chosen)}/{target} from {eligible} relevant candidates; topics={dict(tc)} rejects={dict(rc)}")
    if len(chosen)<target:
        raise SystemExit(2)

if __name__=="__main__":
    main()
