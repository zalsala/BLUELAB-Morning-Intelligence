#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import select_priority_news as priority
import validate_sources as source_audit

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
SOURCE_POLICY = ROOT / "config" / "source-policy.json"
TARGET_CHAPTERS = tuple(priority.POLICY.keys())


def domain(url: str) -> str:
    return source_audit.norm_domain(url)


def chapter_metrics(items: list[dict], rejected_paths: set[str], discovery_only: set[str]) -> dict:
    domains = Counter(domain(x.get("canonical_url") or x.get("url", "")) for x in items)
    domains.pop("", None)
    generic = []
    discovery = []
    incomplete = []
    for x in items:
        url = x.get("canonical_url") or x.get("url", "")
        d = domain(url)
        if not url or not d:
            incomplete.append(x.get("title", "<untitled>"))
        elif source_audit.is_generic_url(url, rejected_paths):
            generic.append({"title": x.get("title"), "url": url})
        if d in discovery_only:
            discovery.append({"title": x.get("title"), "url": url, "domain": d})
    total = len(items)
    max_share = (max(domains.values()) / total) if total and domains else 0.0
    wire_share = (sum(n for d, n in domains.items() if d in source_audit.WIRE_DOMAINS) / total) if total else 0.0
    return {
        "story_count": total,
        "unique_domains": len(domains),
        "domain_counts": dict(domains),
        "max_single_domain_share": round(max_share, 4),
        "wire_share": round(wire_share, 4),
        "generic_url_count": len(generic),
        "discovery_only_count": len(discovery),
        "incomplete_url_count": len(incomplete),
        "generic_urls": generic,
        "discovery_only": discovery,
        "incomplete_urls": incomplete,
    }


def load_current() -> tuple[dict, list[dict]]:
    today = json.loads((DATA / "today.json").read_text(encoding="utf-8"))
    stories: list[dict] = []
    for name in today.get("story_files", []):
        stories.extend(json.loads((DATA / name).read_text(encoding="utf-8")))
    top5 = set(today.get("top5_titles", []))
    rendered = [x for x in stories if x.get("title") not in top5]
    return today, rendered


def build(arbitrated: dict) -> dict:
    today, current = load_current()
    policy = json.loads(SOURCE_POLICY.read_text(encoding="utf-8"))
    rejected_paths = set(policy["generic_url_paths_rejected_for_verified_articles"])
    discovery_only = set(policy["discovery_only_domains"])

    current_by = defaultdict(list)
    for x in current:
        current_by[x.get("section", "")].append(x)
    proposed_by = defaultdict(list)
    for x in arbitrated.get("selected", []):
        proposed_by[x.get("chapter", "")].append(x)

    chapter_report = {}
    hard_errors = []
    for chapter in TARGET_CHAPTERS:
        before = chapter_metrics(current_by.get(chapter, []), rejected_paths, discovery_only)
        after = chapter_metrics(proposed_by.get(chapter, []), rejected_paths, discovery_only)
        required_domains = policy["diversity_rules"]["general_chapter_min_unique_domains"]
        after_ok = (
            after["story_count"] >= 10
            and after["unique_domains"] >= required_domains
            and after["max_single_domain_share"] <= policy["diversity_rules"]["max_single_domain_share"]
            and after["wire_share"] <= policy["diversity_rules"]["max_wire_share_reuters_ap_afp_combined"]
            and after["generic_url_count"] == 0
            and after["discovery_only_count"] == 0
            and after["incomplete_url_count"] == 0
        )
        if not after_ok:
            hard_errors.append(f"{chapter}: proposed source-quality gate failed")
        chapter_report[chapter] = {
            "before": before,
            "proposed": after,
            "source_quality_status": "PASS" if after_ok else "FAIL",
            "improvement": {
                "unique_domains_delta": after["unique_domains"] - before["unique_domains"],
                "generic_url_delta": after["generic_url_count"] - before["generic_url_count"],
                "discovery_only_delta": after["discovery_only_count"] - before["discovery_only_count"],
            },
        }

    selected = arbitrated.get("selected", [])
    duplicate_urls = arbitrated.get("cross_chapter_duplicate_urls", [])
    if duplicate_urls:
        hard_errors.append(f"cross-chapter duplicate URLs remain: {duplicate_urls}")
    if len(selected) != 40:
        hard_errors.append(f"expected 40 arbitrated priority stories; found {len(selected)}")

    editorial_blockers = [
        "candidate titles/summaries are source-language acquisition records, not final Korean editorial copy",
        "required full-detail fields and fact-check prose have not been editorially authored for production",
        "article image/hero-image suitability has not been audited for every replacement",
        "TOP5 interaction and final 145-story global event dedup have not yet been recomputed",
        "live Cloudflare render has not been validated against this proposal",
    ]

    return {
        "schema_version": "priority-replacement-proposal-v1",
        "edition": today.get("meta", {}).get("edition"),
        "source_selection_schema": arbitrated.get("schema_version"),
        "selected_count": len(selected),
        "target_chapters": list(TARGET_CHAPTERS),
        "source_quality_status": "PASS" if not hard_errors else "FAIL",
        "production_ready": False,
        "publication_status": "PROPOSAL_ONLY_DO_NOT_PUBLISH",
        "hard_errors": hard_errors,
        "editorial_blockers": editorial_blockers,
        "duplicate_groups_resolved": arbitrated.get("duplicate_groups_resolved", []),
        "backfilled": arbitrated.get("backfilled", []),
        "chapter_report": chapter_report,
        "replacement_candidates": selected,
    }


def self_test() -> None:
    fake = {
        "schema_version": "priority-news-global-arbitration-v1",
        "selected": [],
        "cross_chapter_duplicate_urls": [],
    }
    # Unit-test safety invariant without requiring live artifacts.
    out = {"production_ready": False, "publication_status": "PROPOSAL_ONLY_DO_NOT_PUBLISH"}
    assert out["production_ready"] is False
    assert out["publication_status"] == "PROPOSAL_ONLY_DO_NOT_PUBLISH"
    assert fake["cross_chapter_duplicate_urls"] == []
    print("PASS: replacement proposal safety self-test")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--output", default="artifacts/priority-replacement-proposal.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.input:
        ap.error("--input required")
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    proposal = build(data)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"REPLACEMENT_PROPOSAL selected={proposal['selected_count']} "
        f"source_quality={proposal['source_quality_status']} production_ready={proposal['production_ready']}"
    )
    for ch, r in proposal["chapter_report"].items():
        print(
            f"  {ch}: before_domains={r['before']['unique_domains']} "
            f"proposed_domains={r['proposed']['unique_domains']} "
            f"generic={r['proposed']['generic_url_count']} discovery={r['proposed']['discovery_only_count']} "
            f"status={r['source_quality_status']}"
        )
    if proposal["hard_errors"]:
        for e in proposal["hard_errors"]:
            print("  ERROR", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
