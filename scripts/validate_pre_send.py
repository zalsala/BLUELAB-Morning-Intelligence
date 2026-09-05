#!/usr/bin/env python3
"""Canonical PRE-SEND validation for the rendered Morning Intelligence bundle."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "public" / "data" / "today.json"
VISION_ID = "vision-research-watch"
EXPECTED_STORY_FILES = [f"stories-{i}.json" for i in range(1, 6)]


def validate_bundle(data: dict, expected_date: str) -> list[str]:
    errors: list[str] = []

    metadata = data.get("metadata") or {}
    if metadata.get("date") != expected_date:
        errors.append(f"edition date mismatch: {metadata.get('date')} != {expected_date}")

    chapters = data.get("chapters") or []
    vision = [c for c in chapters if c.get("id") == VISION_ID]
    general = [c for c in chapters if c.get("id") != VISION_ID]

    if len(general) != 14:
        errors.append(f"general chapter count={len(general)} != 14")
    if len(vision) != 1:
        errors.append(f"vision research chapter count={len(vision)} != 1")
    if len(chapters) != 15:
        errors.append(f"total rendered chapter count={len(chapters)} != 15")

    for chapter in general:
        count = len(chapter.get("articles") or [])
        if count < 10:
            errors.append(f"{chapter.get('name')}: rendered items={count} < 10")

    if vision:
        vision_count = len(vision[0].get("articles") or [])
        if vision_count != 10:
            errors.append(f"VISION RESEARCH WATCH rendered items={vision_count} != 10")

    general_articles = [a for chapter in general for a in (chapter.get("articles") or [])]
    all_articles = general_articles + ((vision[0].get("articles") or []) if vision else [])
    if len(general_articles) != 140:
        errors.append(f"general article count={len(general_articles)} != 140")
    if len(all_articles) != 150:
        errors.append(f"total rendered article count={len(all_articles)} != 150")

    article_urls = [a.get("link", "") for a in all_articles]
    if len(article_urls) != len(set(article_urls)):
        errors.append("cross-chapter exact URL duplicates remain")

    top5 = data.get("top_5_highlights") or []
    if len(top5) != 5:
        errors.append(f"TOP5 count={len(top5)} != 5")

    videos = data.get("youtube_hot_issues") or []
    channels = {v.get("channel") for v in videos if v.get("channel")}
    if len(videos) < 10:
        errors.append(f"YouTube count={len(videos)} < 10")
    if len(channels) < 4:
        errors.append(f"YouTube unique channels={len(channels)} < 4")

    urls = article_urls + [a.get("link", "") for a in top5]
    google_news = [u for u in urls if urlparse(u).netloc.lower().endswith("news.google.com")]
    if google_news:
        errors.append(f"exact article URL gate: {len(google_news)} Google News relay URLs remain")

    trends = data.get("trending_keywords") or []
    if len(trends) not in (0, 20):
        errors.append(f"trending keyword count must be 0 or 20; found {len(trends)}")

    if len(data.get("three_line_summary") or []) != 3:
        errors.append("final summary must contain exactly 3 lines")

    weather = data.get("weather") or {}
    if not weather.get("source") or not weather.get("source_level"):
        errors.append("weather source/source_level missing")

    if metadata.get("story_files") != EXPECTED_STORY_FILES:
        errors.append("exactly five active story bundles are required")

    if vision:
        domains: set[str] = set()
        for article in vision[0].get("articles") or []:
            research = article.get("research_watch") or {}
            for key in (
                "evidence_type",
                "study_design",
                "clinical_meaning_ko",
                "limitations_conflicts_ko",
                "exact_source_url",
            ):
                if not research.get(key):
                    errors.append(f"VISION RESEARCH WATCH missing {key}: {article.get('title', '')}")
            hostname = urlparse(research.get("exact_source_url") or article.get("link", "")).hostname
            if hostname:
                domains.add(hostname.lower().removeprefix("www."))
        if len(domains) < 5:
            errors.append(f"VISION RESEARCH WATCH source domains={len(domains)} < 5")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--expected-date")
    parser.add_argument("--expected-today-kst", action="store_true")
    args = parser.parse_args()

    expected_date = args.expected_date
    if args.expected_today_kst:
        kst_today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        if expected_date and expected_date != kst_today:
            raise SystemExit(f"conflicting expected dates: {expected_date} != {kst_today}")
        expected_date = kst_today
    if not expected_date:
        raise SystemExit("--expected-date or --expected-today-kst is required")

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    errors = validate_bundle(data, expected_date)
    if errors:
        print("PRE_SEND_QA=FAIL")
        for error in errors:
            print(" -", error)
        raise SystemExit(2)
    print("PRE_SEND_QA=PASS")


if __name__ == "__main__":
    main()
