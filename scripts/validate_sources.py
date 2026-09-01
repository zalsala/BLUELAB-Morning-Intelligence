from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
POLICY = ROOT / "config" / "source-policy.json"
WIRE_DOMAINS = {"reuters.com", "apnews.com", "afp.com"}
SPECIALIST = {
    "과학",
    "안경 · 콘택트렌즈 · 안과 · 검안 · 시과학 · 근시관리",
    "의료 · 헬스케어",
}


def norm_domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_generic_url(url: str, rejected_paths: set[str]) -> bool:
    parsed = urlparse(url or "")
    path = parsed.path or "/"
    return path in rejected_paths


def load() -> tuple[dict, dict, list[dict]]:
    today = json.loads((DATA / "today.json").read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    files = today.get("story_files", [])
    if files != [f"stories-{i}.json" for i in range(1, 6)]:
        raise SystemExit("FAIL: today.json must reference exactly stories-1.json..stories-5.json")
    stories: list[dict] = []
    for name in files:
        stories.extend(json.loads((DATA / name).read_text(encoding="utf-8")))
    return today, policy, stories


def audit(strict: bool) -> int:
    today, policy, stories = load()
    rules = policy["diversity_rules"]
    rejected = set(policy["generic_url_paths_rejected_for_verified_articles"])
    discovery_only = set(policy["discovery_only_domains"])
    top5 = set(today.get("top5_titles", []))

    errors: list[str] = []
    warnings: list[str] = []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for story in stories:
        grouped[story.get("section", "")].append(story)

    for section, cfg in policy["chapters"].items():
        items = grouped.get(section, [])
        rendered = [x for x in items if x.get("title") not in top5]
        domains = Counter(norm_domain(x.get("url", "")) for x in rendered if norm_domain(x.get("url", "")))
        unique = len(domains)
        required = rules["specialist_chapter_min_unique_domains"] if section in SPECIALIST else rules["general_chapter_min_unique_domains"]

        if rendered and unique < required:
            msg = f"{section}: unique domains {unique} < {required} ({dict(domains)})"
            (errors if strict else warnings).append(msg)

        if rendered:
            max_share = max(domains.values(), default=0) / len(rendered)
            if max_share > rules["max_single_domain_share"]:
                msg = f"{section}: largest domain share {max_share:.0%} > {rules['max_single_domain_share']:.0%}"
                (errors if strict else warnings).append(msg)
            wire = sum(n for d, n in domains.items() if d in WIRE_DOMAINS) / len(rendered)
            if wire > rules["max_wire_share_reuters_ap_afp_combined"]:
                msg = f"{section}: Reuters/AP/AFP share {wire:.0%} > {rules['max_wire_share_reuters_ap_afp_combined']:.0%}"
                (errors if strict else warnings).append(msg)

        preferred = set(cfg.get("preferred_domains", []))
        off_policy = [d for d in domains if d and d not in preferred and d not in discovery_only]
        if off_policy:
            warnings.append(f"{section}: review unclassified domains: {', '.join(sorted(off_policy))}")

    for story in stories:
        url = story.get("url", "")
        domain = norm_domain(url)
        if not url or not domain:
            errors.append(f"missing source URL: {story.get('title', '<untitled>')}")
            continue
        if domain in discovery_only and story.get("section") not in {
            "유튜브 · 숏츠",
            "핫이슈 · 바이럴 · 밈 · 온라인/소셜 트렌드",
        }:
            msg = f"discovery-only source used as final article: {domain} | {story.get('title')}"
            (errors if strict else warnings).append(msg)
        if is_generic_url(url, rejected):
            msg = f"generic/home/section URL requires exact-article replacement: {url} | {story.get('title')}"
            (errors if strict else warnings).append(msg)

    print(f"SOURCE_AUDIT edition={today.get('meta', {}).get('edition', today.get('meta', {}).get('date', 'unknown'))}")
    for section in policy["chapters"]:
        rendered = [x for x in grouped.get(section, []) if x.get("title") not in top5]
        domains = Counter(norm_domain(x.get("url", "")) for x in rendered if norm_domain(x.get("url", "")))
        print(f"  {section}: {len(rendered)} rendered stories / {len(domains)} unique domains")

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("PASS: source audit completed" + (" in strict mode" if strict else " in report mode"))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Fail on diversity and generic/discovery-only source violations")
    args = parser.parse_args()
    raise SystemExit(audit(args.strict))
