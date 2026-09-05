#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
EXPECTED_FILES = [f"stories-{i}.json" for i in range(1, 6)]
PLACEHOLDER = re.compile(r"(^|\W)(undefined|null|tbd|todo|placeholder)(\W|$)", re.I)
KST = ZoneInfo("Asia/Seoul")


def valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value or "")
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def audit(release: bool = False, expected_date: str | None = None) -> int:
    today = json.loads((DATA / "today.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "publication_manifest.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    metadata = today.get("metadata", {})
    date = metadata.get("date")
    expected = expected_date or datetime.now(KST).strftime("%Y-%m-%d")
    if date != expected:
        errors.append(f"edition date mismatch: {date} != {expected}")

    chapters = today.get("chapters", [])
    if len(chapters) != 14:
        errors.append(f"chapter count={len(chapters)} != 14")
    articles = []
    for chapter in chapters:
        chapter_articles = chapter.get("articles", [])
        if len(chapter_articles) < 10:
            errors.append(f"{chapter.get('name')}: rendered items={len(chapter_articles)} < 10")
        articles.extend(chapter_articles)
    if len(articles) < 140:
        errors.append(f"rendered article total={len(articles)} < 140")

    urls = [a.get("link", "") for a in articles]
    if len(urls) != len(set(urls)):
        errors.append("cross-chapter duplicate article URLs remain")
    for idx, url in enumerate(urls, 1):
        if not valid_http_url(url):
            errors.append(f"article {idx} missing valid exact URL")
        elif urlparse(url).netloc.lower().endswith("news.google.com"):
            errors.append(f"article {idx} still uses Google News relay URL")

    top5 = today.get("top_5_highlights", [])
    if len(top5) != 5 or len({x.get('id') for x in top5}) != 5:
        errors.append("TOP5 must contain exactly five unique items")

    story_files = metadata.get("story_files", [])
    if story_files != EXPECTED_FILES:
        errors.append(f"metadata.story_files must equal {EXPECTED_FILES}")
    else:
        bundled = []
        for name in story_files:
            chunk = json.loads((DATA / name).read_text(encoding="utf-8"))
            if not isinstance(chunk, list):
                errors.append(f"{name} must contain a JSON list")
            else:
                bundled.extend(chunk)
        if len(bundled) != 140:
            errors.append(f"story bundle total={len(bundled)} != 140")

    trends = today.get("trending_keywords", [])
    trends_source = metadata.get("trends_source")
    if len(trends) == 20:
        if trends_source != "Google Trends KR official RSS":
            errors.append("20 Trends entries require official Google Trends KR RSS provenance")
    elif len(trends) == 0:
        if trends_source != "WITHHELD_INSUFFICIENT_RELIABLE_TERMS":
            errors.append("withheld Trends requires explicit insufficiency status")
    else:
        errors.append(f"Trends must be exactly 20 reliable entries or 0 withheld; found {len(trends)}")

    weather = today.get("weather") or {}
    for key in ["location", "temp_current", "temp_min", "temp_max", "condition", "precipitation_prob"]:
        if weather.get(key) is None or weather.get(key) == "":
            errors.append(f"weather missing: {key}")

    market = today.get("market") or {}
    for key in ["kospi", "usd_krw"]:
        if market.get(key) is None:
            errors.append(f"market missing: {key}")

    videos = today.get("youtube_hot_issues", [])
    if len(videos) < 10:
        errors.append(f"YouTube/Shorts count={len(videos)} < 10")
    for idx, video in enumerate(videos, 1):
        url = video.get("url") or video.get("video_url") or video.get("source_url")
        if not valid_http_url(url):
            errors.append(f"video {idx} missing valid URL")

    if len(today.get("next_signals", [])) < 3:
        errors.append("NEXT SIGNALS must contain at least 3 items")
    if len(today.get("three_line_summary", [])) != 3:
        errors.append("three_line_summary must contain exactly 3 lines")

    if manifest.get("edition_date") != expected:
        errors.append(f"manifest edition mismatch: {manifest.get('edition_date')} != {expected}")
    if manifest.get("canonical_status") != "CANONICAL_PASS":
        errors.append(f"manifest canonical_status={manifest.get('canonical_status')} != CANONICAL_PASS")
    manifest_fp = today.get("publication_manifest_fingerprint")
    if not manifest_fp or manifest_fp != manifest.get("manifest_sha256"):
        errors.append("today.json publication manifest fingerprint mismatch")

    if release:
        def walk(value, path="today"):
            if isinstance(value, dict):
                for key, child in value.items():
                    walk(child, f"{path}.{key}")
            elif isinstance(value, list):
                for idx, child in enumerate(value):
                    walk(child, f"{path}[{idx}]")
            elif isinstance(value, str) and PLACEHOLDER.search(value):
                errors.append(f"placeholder token in {path}: {value[:80]}")
        walk(today)

    mode = "RELEASE" if release else "STRUCTURAL"
    print(f"CONTRACT_{mode} edition={date}")
    if errors:
        print("ERRORS:")
        for error in errors:
            print("  -", error)
        return 1
    print(f"PASS: contract {mode.lower()} gate")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--expected-date", default=None)
    parser.add_argument("--expected-today-kst", action="store_true")
    args = parser.parse_args()
    expected = datetime.now(KST).strftime("%Y-%m-%d") if args.expected_today_kst else args.expected_date
    if args.expected_today_kst and args.expected_date and args.expected_date != expected:
        print(f"ERROR: explicit expected-date {args.expected_date} conflicts with KST today {expected}")
        return 2
    return audit(args.release, expected)


if __name__ == "__main__":
    sys.exit(main())
