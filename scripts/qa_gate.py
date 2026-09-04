"""Strict production QA for BLUELAB Morning Intelligence."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.schema import FACT_CHECK_STATES
from pipeline.top5_ranker import is_top5_title_eligible

EXPECTED_CHAPTER_COUNT = 14
EXPECTED_ARTICLES_PER_CHAPTER = 10
EXPECTED_TOTAL_ARTICLES = 140
EXPECTED_TOP5_COUNT = 5
ALLOWED_BODY_VALIDATION_STATES = {
    "VALIDATED", "EVENT_MISMATCH", "NO_QUALIFIED_BODY", "HTTP_403", "HTTP_404", "TIMEOUT"
}


def run_qa_gate(json_path: str = "public/data/today.json") -> bool:
    print("=" * 75)
    print(" [QA GATE] BLUELAB Morning Intelligence 엄격 품질 검사 시작")
    print("=" * 75)
    failures: List[str] = []

    if not os.path.exists(json_path):
        print(f" [FAIL] missing file: {json_path}")
        return False
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f" [FAIL] JSON parse error: {exc}")
        return False

    chapters = data.get("chapters", [])
    if len(chapters) != EXPECTED_CHAPTER_COUNT:
        failures.append(f"chapter count={len(chapters)} != {EXPECTED_CHAPTER_COUNT}")

    all_articles = []
    for ch in chapters:
        arts = ch.get("articles", [])
        all_articles.extend(arts)
        if len(arts) != EXPECTED_ARTICLES_PER_CHAPTER:
            failures.append(f"{ch.get('name')}: article count={len(arts)} != 10")
    if len(all_articles) != EXPECTED_TOTAL_ARTICLES:
        failures.append(f"total articles={len(all_articles)} != 140")

    ids = [a.get("id", "") for a in all_articles]
    urls = [a.get("link", "") for a in all_articles]
    titles = [a.get("title", "") for a in all_articles]
    for label, values in (("id", ids), ("url", urls), ("title", titles)):
        if any(not x for x in values):
            failures.append(f"missing article {label}")
        if len(values) != len(set(values)):
            failures.append(f"duplicate article {label}")

    article_ids = set(ids)
    article_urls = set(urls)

    # Exact Article URL Gate
    google_news_relay = [u for u in urls if urlparse(u).netloc.lower().endswith("news.google.com")]
    if google_news_relay:
        failures.append(f"exact article URL gate: {len(google_news_relay)} Google News relay URLs remain")

    verified_image_hashes = []
    for art in all_articles:
        ed = art.get("editorial", {})
        if len((ed.get("fact") or "").strip()) < 10:
            failures.append(f"editorial fact incomplete: {art.get('title','')[:30]}")
        if len((ed.get("background") or "").strip()) < 10:
            failures.append(f"editorial background incomplete: {art.get('title','')[:30]}")
        if len((ed.get("why_it_matters") or "").strip()) < 10:
            failures.append(f"editorial why incomplete: {art.get('title','')[:30]}")
        if len(ed.get("checkpoints") or []) < 2:
            failures.append(f"editorial checkpoints incomplete: {art.get('title','')[:30]}")

        # Fact Check + Article Body Validation Gate
        fc = art.get("fact_check")
        if not fc or not isinstance(fc, dict):
            failures.append(f"missing fact_check data: {art.get('title','')[:30]}")
        else:
            fc_status = fc.get("status")
            if fc_status not in FACT_CHECK_STATES:
                failures.append(f"invalid fact_check status {fc_status!r}: {art.get('title','')[:30]}")
            body_validation = fc.get("body_validation")
            if not isinstance(body_validation, dict):
                failures.append(f"missing body_validation data: {art.get('title','')[:30]}")
            else:
                body_status = body_validation.get("status")
                if body_status not in ALLOWED_BODY_VALIDATION_STATES:
                    failures.append(f"invalid body_validation status {body_status!r}: {art.get('title','')[:30]}")

        # Image Provenance Gate
        img = art.get("image")
        if not img or not isinstance(img, dict):
            failures.append(f"missing image provenance structure: {art.get('title','')[:30]}")
        else:
            img_status = img.get("status")
            if img_status not in ("VERIFIED_PROVENANCE", "EXPLICIT_NULL"):
                failures.append(f"invalid image provenance status {img_status!r}: {art.get('title','')[:30]}")
            if img_status == "EXPLICIT_NULL" and img.get("url") is not None:
                failures.append(f"EXPLICIT_NULL must have url=None: {art.get('title','')[:30]}")
            if img_status == "VERIFIED_PROVENANCE":
                if not img.get("url"):
                    failures.append(f"VERIFIED_PROVENANCE missing url: {art.get('title','')[:30]}")
                if not img.get("content_hash"):
                    failures.append(f"VERIFIED_PROVENANCE missing content_hash: {art.get('title','')[:30]}")
                else:
                    verified_image_hashes.append(img.get("content_hash"))
                if not img.get("declaration_method"):
                    failures.append(f"VERIFIED_PROVENANCE missing declaration_method: {art.get('title','')[:30]}")
                if not img.get("source_domain") or not img.get("article_domain"):
                    failures.append(f"VERIFIED_PROVENANCE missing domain provenance: {art.get('title','')[:30]}")

    if len(verified_image_hashes) != len(set(verified_image_hashes)):
        failures.append("duplicate VERIFIED_PROVENANCE image content_hash remains")

    weather = data.get("weather") or {}
    if "인천 서구 검단" not in weather.get("location", "") or "temp_current" not in weather:
        failures.append("Geomdan weather missing/incomplete")

    top5 = data.get("top_5_highlights", [])
    if len(top5) != EXPECTED_TOP5_COUNT:
        failures.append("TOP5 must contain exactly 5 items")
    top5_ids = [a.get("id", "") for a in top5]
    top5_urls = [a.get("link", "") for a in top5]
    if any(not x for x in top5_ids) or len(top5_ids) != len(set(top5_ids)):
        failures.append("TOP5 ids must be present and unique")
    if any(article_id not in article_ids for article_id in top5_ids):
        failures.append("TOP5 contains item not present in canonical 140-article snapshot")
    if any(url not in article_urls for url in top5_urls):
        failures.append("TOP5 contains URL not present in canonical 140-article snapshot")
    top5_google_news = [u for u in top5_urls if urlparse(u).netloc.lower().endswith("news.google.com")]
    if top5_google_news:
        failures.append(f"TOP5 exact URL gate: {len(top5_google_news)} Google News relay URLs in TOP5")
    ineligible_top5 = [a.get("title", "") for a in top5 if not is_top5_title_eligible(a.get("title", ""))]
    if ineligible_top5:
        failures.append(f"TOP5 factual-news gate: {len(ineligible_top5)} opinion/editorial items remain")
    top5_chapters = [a.get("chapter_id", "") for a in top5]
    if len(top5) == EXPECTED_TOP5_COUNT and len(set(top5_chapters)) != EXPECTED_TOP5_COUNT:
        failures.append("TOP5 chapter diversity gate: expected 5 distinct chapters")

    # Financial Market Block Gate
    market = data.get("market") or {}
    if not market or "kospi" not in market or "usd_krw" not in market:
        failures.append("financial market block missing/incomplete")

    # NEXT SIGNALS Gate
    next_signals = data.get("next_signals") or []
    if len(next_signals) < 3:
        failures.append(f"NEXT SIGNALS count={len(next_signals)} < 3")

    # Official Google Trends KR is fail-closed: publish exactly 20 reliable terms,
    # or publish none. Never synthesize/fill missing positions.
    trends = data.get("trending_keywords", [])
    if len(trends) not in (0, 20):
        failures.append(f"Google Trends count must be 0 or 20; found {len(trends)}")
    trends_source = data.get("metadata", {}).get("trends_source", "")
    if len(trends) == 0 and trends_source != "WITHHELD_INSUFFICIENT_RELIABLE_TERMS":
        failures.append("withheld Trends must carry explicit insufficiency status")
    if len(trends) == 20 and trends_source != "Google Trends KR official RSS":
        failures.append("20 Trends terms must be sourced from official Google Trends KR RSS")

    if len(data.get("three_line_summary", [])) != 3:
        failures.append("final summary must contain exactly 3 lines")
    if len(data.get("youtube_hot_issues", [])) < 10:
        failures.append("YouTube/Shorts must contain at least 10 verified records")
    if len({v.get("channel") for v in data.get("youtube_hot_issues", []) if v.get("channel")}) < 4:
        failures.append("YouTube/Shorts must span at least 4 channels")
    if len(data.get("integrity_hash", "")) < 32:
        failures.append("integrity_hash missing/invalid")

    if failures:
        print(" [QA GATE REJECTED]")
        for idx, failure in enumerate(failures[:50], 1):
            print(f"  {idx}. {failure}")
        return False

    print(" [QA GATE PASSED]")
    print(f"  chapters=14 articles=140 top5=5 youtube={len(data.get('youtube_hot_issues', []))} trends={len(trends)} summary_lines=3 market=PASS signals={len(next_signals)}")
    return True


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "public/data/today.json"
    raise SystemExit(0 if run_qa_gate(target) else 1)
