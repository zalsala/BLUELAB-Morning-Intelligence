from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"public"/"data"
POLICY=ROOT/"config"/"source-policy.json"
VISION_POLICY=ROOT/"config"/"vision-research-policy.json"
WIRE_DOMAINS={"reuters.com","apnews.com","afp.com"}
EXPECTED_FILES=[f"stories-{i}.json" for i in range(1,6)]
VISION_ID="vision-research-watch"


def norm_domain(url:str)->str:
    host=urlparse(url or "").netloc.lower(); return host[4:] if host.startswith("www.") else host

def is_generic_url(url:str,rejected_paths:set[str])->bool:
    parsed=urlparse(url or ""); return (parsed.path or "/") in rejected_paths

def load()->tuple[dict,dict,dict,list[dict]]:
    today=json.loads((DATA/"today.json").read_text(encoding="utf-8")); policy=json.loads(POLICY.read_text(encoding="utf-8")); vpolicy=json.loads(VISION_POLICY.read_text(encoding="utf-8"))
    files=today.get("metadata",{}).get("story_files",[])
    if files!=EXPECTED_FILES: raise SystemExit(f"FAIL: metadata.story_files must equal {EXPECTED_FILES}")
    stories=[]
    for name in files:
        chunk=json.loads((DATA/name).read_text(encoding="utf-8"))
        if not isinstance(chunk,list): raise SystemExit(f"FAIL: {name} must contain a JSON list")
        stories.extend(chunk)
    return today,policy,vpolicy,stories

def audit(strict:bool)->int:
    today,policy,vpolicy,stories=load(); rules=policy["diversity_rules"]; rejected=set(policy["generic_url_paths_rejected_for_verified_articles"]); discovery_only=set(policy["discovery_only_domains"])
    errors=[]; warnings=[]; grouped=defaultdict(list)
    for story in stories: grouped[story.get("section","")].append(story)

    chapters=today.get("chapters",[]); general=[ch for ch in chapters if ch.get("id")!=VISION_ID]; vision=[ch for ch in chapters if ch.get("id")==VISION_ID]
    expected_sections=[ch.get("name","") for ch in general]
    if len(expected_sections)!=14 or any(not x for x in expected_sections): errors.append(f"general production chapter contract invalid: expected 14 named chapters, found {len(expected_sections)}")
    if vision and len(vision)!=1: errors.append(f"VISION RESEARCH WATCH chapter count={len(vision)} != 1")
    if len(stories)!=140: errors.append(f"story bundle count={len(stories)} != 140")

    seen=set(); dup=[]
    for story in stories:
        u=story.get("url","")
        if u in seen: dup.append(u)
        seen.add(u)
    if dup: errors.append(f"cross-chapter duplicate URLs remain: {len(dup)}")

    for section in expected_sections:
        items=grouped.get(section,[]); domains=Counter(norm_domain(x.get("url","")) for x in items if norm_domain(x.get("url",""))); unique=len(domains); required=rules["general_chapter_min_unique_domains"]
        if len(items)!=10: errors.append(f"{section}: story bundle items={len(items)} != 10")
        if items and unique<required:
            msg=f"{section}: unique domains {unique} < {required} ({dict(domains)})"; (errors if strict else warnings).append(msg)
        if items:
            max_share=max(domains.values(),default=0)/len(items)
            if max_share>rules["max_single_domain_share"]:
                msg=f"{section}: largest domain share {max_share:.0%} > {rules['max_single_domain_share']:.0%}"; (errors if strict else warnings).append(msg)
            wire=sum(n for d,n in domains.items() if d in WIRE_DOMAINS)/len(items)
            if wire>rules["max_wire_share_reuters_ap_afp_combined"]:
                msg=f"{section}: Reuters/AP/AFP share {wire:.0%} > {rules['max_wire_share_reuters_ap_afp_combined']:.0%}"; (errors if strict else warnings).append(msg)

    for story in stories:
        url=story.get("url",""); domain=norm_domain(url)
        if not url or not domain: errors.append(f"missing source URL: {story.get('title','<untitled>')}"); continue
        parsed=urlparse(url)
        if parsed.scheme not in {"http","https"}: errors.append(f"non-http source URL: {url}")
        if domain in discovery_only:
            msg=f"discovery-only source used as final article: {domain} | {story.get('title')}"; (errors if strict else warnings).append(msg)
        if is_generic_url(url,rejected):
            msg=f"generic/home/section URL requires exact-article replacement: {url} | {story.get('title')}"; (errors if strict else warnings).append(msg)

    if vision:
        rows=vision[0].get("articles",[]); domains=Counter(norm_domain((a.get("research_watch") or {}).get("exact_source_url") or a.get("link","")) for a in rows)
        domains.pop("",None); required=int(vpolicy.get("minimum_unique_source_domains",5))
        if len(rows)!=10: errors.append(f"VISION RESEARCH WATCH: records={len(rows)} != 10")
        if len(domains)<required: errors.append(f"VISION RESEARCH WATCH: unique domains {len(domains)} < {required} ({dict(domains)})")
        for a in rows:
            rw=a.get("research_watch") or {}; u=rw.get("exact_source_url") or a.get("link",""); domain=norm_domain(u)
            if not u or not domain: errors.append(f"VISION RESEARCH WATCH missing exact source URL: {a.get('title')}")
            if domain in discovery_only: errors.append(f"VISION RESEARCH WATCH discovery-only source: {domain} | {a.get('title')}")

    print(f"SOURCE_QA edition={today.get('metadata',{}).get('date','unknown')}")
    for section in expected_sections:
        items=grouped.get(section,[]); domains=Counter(norm_domain(x.get("url","")) for x in items if norm_domain(x.get("url",""))); print(f"  {section}: {len(items)} stories / {len(domains)} unique domains")
    if vision:
        vdomains={norm_domain((a.get('research_watch') or {}).get('exact_source_url') or a.get('link','')) for a in vision[0].get('articles',[])}; vdomains.discard(""); print(f"  VISION RESEARCH WATCH: {len(vision[0].get('articles',[]))} records / {len(vdomains)} unique domains")
    if warnings:
        print("WARNINGS:"); [print("  -",w) for w in warnings]
    if errors:
        print("ERRORS:"); [print("  -",e) for e in errors]; return 1
    print("PASS: source QA completed"+(" in strict mode" if strict else " in report mode")); return 0

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--strict",action="store_true"); a=p.parse_args(); raise SystemExit(audit(a.strict))
