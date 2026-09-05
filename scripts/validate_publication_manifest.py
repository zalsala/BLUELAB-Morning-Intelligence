#!/usr/bin/env python3
"""Validate BLUELAB Morning Intelligence publication manifest continuity."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VISION_ID = "vision-research-watch"


def validate_manifest(manifest_path: Path, today_json_path: Path, expected_date: str | None = None) -> tuple[bool, list[str]]:
    failures=[]
    if not manifest_path.exists(): return False,[f"manifest file missing: {manifest_path}"]
    if not today_json_path.exists(): return False,[f"today.json file missing: {today_json_path}"]
    try: manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc: return False,[f"invalid manifest JSON: {exc}"]
    try: today_data=json.loads(today_json_path.read_text(encoding="utf-8"))
    except Exception as exc: return False,[f"invalid today.json: {exc}"]

    edition_date=manifest.get("edition_date")
    if expected_date and edition_date!=expected_date: failures.append(f"manifest edition date mismatch: {edition_date} != {expected_date}")
    if manifest.get("timezone")!="Asia/Seoul": failures.append(f"manifest timezone must be Asia/Seoul; found {manifest.get('timezone')}")
    source_main_sha=manifest.get("source_main_sha","")
    if len(source_main_sha)!=40: failures.append(f"invalid source_main_sha: {source_main_sha}")

    fps=manifest.get("fingerprints",{}); prod_fp=fps.get("production_fingerprint_sha256")
    if not prod_fp or len(prod_fp)!=64: failures.append("production_fingerprint_sha256 missing or malformed")
    copy_d=dict(today_data); copy_d.pop("publication_manifest_fingerprint",None)
    expected_prod_fp=hashlib.sha256(json.dumps(copy_d,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if prod_fp!=expected_prod_fp: failures.append(f"production fingerprint mismatch: manifest={prod_fp} != recomputed={expected_prod_fp}")

    saved_sha=manifest.get("manifest_sha256"); body=dict(manifest); body.pop("manifest_sha256",None)
    computed_sha=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if saved_sha!=computed_sha: failures.append(f"manifest_sha256 integrity mismatch: {saved_sha} != {computed_sha}")

    counts=manifest.get("content_counts",{})
    vision_declared="vision_research_watch" in counts
    expected_chapters=15 if vision_declared else 14
    expected_articles=150 if vision_declared else 140
    if counts.get("total_chapters")!=expected_chapters: failures.append(f"content_counts.total_chapters={counts.get('total_chapters')} != {expected_chapters}")
    if counts.get("total_articles")!=expected_articles: failures.append(f"content_counts.total_articles={counts.get('total_articles')} != {expected_articles}")
    if vision_declared:
        if counts.get("general_chapters")!=14: failures.append(f"content_counts.general_chapters={counts.get('general_chapters')} != 14")
        if counts.get("general_articles")!=140: failures.append(f"content_counts.general_articles={counts.get('general_articles')} != 140")
        if counts.get("vision_research_watch")!=10: failures.append(f"content_counts.vision_research_watch={counts.get('vision_research_watch')} != 10")
        vchap=[c for c in today_data.get("chapters",[]) if c.get("id")==VISION_ID]
        if len(vchap)!=1: failures.append(f"today.json requires exactly one {VISION_ID} chapter; found {len(vchap)}")
        else:
            rows=vchap[0].get("articles",[])
            if len(rows)!=10: failures.append(f"VISION RESEARCH WATCH articles={len(rows)} != 10")
            domains=set()
            for row in rows:
                rw=row.get("research_watch") or {}; url=rw.get("exact_source_url") or row.get("link","")
                host=(urlparse(url).hostname or "").lower().removeprefix("www.")
                if host: domains.add(host)
                for key in ("evidence_type","study_design","clinical_meaning_ko","limitations_conflicts_ko","exact_source_url"):
                    if not rw.get(key): failures.append(f"VISION RESEARCH WATCH missing {key}: {row.get('title','')}")
            if len(domains)<5: failures.append(f"VISION RESEARCH WATCH unique source domains {len(domains)} < 5: {sorted(domains)}")
        watch_file=today_json_path.parent/"vision-research-watch.json"
        if not watch_file.exists(): failures.append("vision-research-watch.json missing")
        else:
            try:
                watch=json.loads(watch_file.read_text(encoding="utf-8"))
                if watch.get("selected_count")!=10 or watch.get("coverage_status")!="PASS": failures.append("vision-research-watch.json coverage is not PASS/10")
            except Exception as exc: failures.append(f"invalid vision-research-watch.json: {exc}")

    if counts.get("top5")!=5: failures.append(f"content_counts.top5={counts.get('top5')} != 5")
    if (counts.get("youtube") or 0)<10: failures.append(f"content_counts.youtube={counts.get('youtube')} < 10")
    if counts.get("trends") not in (0,20): failures.append(f"content_counts.trends={counts.get('trends')} not in (0, 20)")
    if counts.get("summary_lines")!=3: failures.append(f"content_counts.summary_lines={counts.get('summary_lines')} != 3")

    story_declared="story_bundles" in counts or "story_files" in today_data.get("metadata",{})
    if story_declared:
        if counts.get("story_bundles")!=5: failures.append(f"content_counts.story_bundles={counts.get('story_bundles')} != 5")
        try:
            from pipeline.story_bundle_writer import validate_story_bundles
            failures.extend(validate_story_bundles(today_json_path,today_json_path.parent))
        except Exception as exc: failures.append(f"story bundle validator error: {exc}")
        expected=[f"stories-{i}.json" for i in range(1,6)]
        if today_data.get("metadata",{}).get("story_files")!=expected: failures.append(f"today metadata.story_files must be exactly {expected}; found {today_data.get('metadata',{}).get('story_files')}")
    return len(failures)==0,failures


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--manifest",default=str(ROOT/"public/data/publication_manifest.json")); p.add_argument("--today",default=str(ROOT/"public/data/today.json")); p.add_argument("--expected-date",default=None); a=p.parse_args()
    passed,errors=validate_manifest(Path(a.manifest),Path(a.today),a.expected_date)
    if not passed:
        print("[PUBLICATION MANIFEST AUDIT REJECTED]")
        for e in errors: print(" -",e)
        return 1
    print("[PUBLICATION MANIFEST AUDIT PASSED] fingerprint + five story bundles + specialist watch continuity verified")
    return 0

if __name__=="__main__": sys.exit(main())
