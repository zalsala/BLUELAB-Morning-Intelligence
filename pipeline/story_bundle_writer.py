"""Write and validate the five canonical active story bundles.

The legacy/publication contract expects exactly five ``stories-N.json`` files.
They are deterministic projections of the 140 selected articles in today.json;
no new editorial content is invented here.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "public" / "data"
EXPECTED_FILES = [f"stories-{i}.json" for i in range(1, 6)]


def _fact_status(article: Any) -> str:
    fc = getattr(article, "fact_check", None) or {}
    state = (fc.get("status") or "UNVERIFIED").upper()
    if state in {"VERIFIED_OFFICIAL", "VERIFIED_PRIMARY", "VERIFIED_MULTI_SOURCE"}:
        return "CONFIRMED"
    if state in {"PARTIAL", "ACCESS_BLOCKED"}:
        return "PARTIALLY CONFIRMED"
    if state == "CONFLICT":
        return "DISPUTED"
    return "UNVERIFIED"


def _freshness(article: Any, edition_date: str) -> str:
    published = (getattr(article, "published_at", "") or "")[:10]
    try:
        age = (datetime.fromisoformat(edition_date).date() - datetime.fromisoformat(published).date()).days
    except Exception:
        return "발행일 확인 필요"
    if age <= 1:
        return "NEW SINCE LAST BRIEFING"
    if age <= 3:
        return "최근 3일 보완"
    if age <= 7:
        return "최근 7일 보완"
    return "전문분야 최근 30일 보완"


def _story(article: Any, edition_date: str) -> dict[str, Any]:
    editorial = getattr(article, "editorial", None)
    fact = getattr(editorial, "fact", "") if editorial is not None else ""
    raw = getattr(article, "summary_raw", "") or ""
    summary = (fact or raw).strip()
    return {
        "section": getattr(article, "chapter_name", ""),
        "title": getattr(article, "title", ""),
        "summary": summary,
        "source": getattr(article, "source", ""),
        "url": getattr(article, "link", ""),
        "date": (getattr(article, "published_at", "") or "")[:10],
        "status": _fact_status(article),
        "freshness_note": _freshness(article, edition_date),
    }


def write_story_bundles(bundle: Any, data_dir: Path = DATA_DIR) -> list[str]:
    """Project the selected 140 articles into exactly five 28-record files."""
    data_dir.mkdir(parents=True, exist_ok=True)
    articles = [a for chapter in bundle.chapters for a in chapter.articles]
    if len(articles) != 140:
        raise ValueError(f"story bundle contract requires exactly 140 articles; found {len(articles)}")

    edition_date = bundle.metadata.get("date") or datetime.now(KST).strftime("%Y-%m-%d")
    stories = [_story(a, edition_date) for a in articles]
    if len({s["url"] for s in stories}) != 140:
        raise ValueError("story bundle contract requires 140 unique article URLs")

    for idx, name in enumerate(EXPECTED_FILES):
        chunk = stories[idx * 28:(idx + 1) * 28]
        if len(chunk) != 28:
            raise ValueError(f"{name}: expected 28 records; found {len(chunk)}")
        (data_dir / name).write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")

    # Fail closed if stale/extra numbered story bundles exist.
    extras = sorted(p.name for p in data_dir.glob("stories-*.json") if p.name not in EXPECTED_FILES)
    if extras:
        raise ValueError(f"unexpected story bundle files: {extras}")
    print("  [story bundles] stories-1..5.json written: 28 x 5 = 140")
    return EXPECTED_FILES.copy()


def validate_story_bundles(today_path: Path = DATA_DIR / "today.json", data_dir: Path = DATA_DIR) -> list[str]:
    errors: list[str] = []
    files = sorted(p.name for p in data_dir.glob("stories-*.json"))
    if files != EXPECTED_FILES:
        errors.append(f"active story bundles must be exactly {EXPECTED_FILES}; found {files}")
        return errors

    today = json.loads(today_path.read_text(encoding="utf-8"))
    today_articles = [a for ch in today.get("chapters", []) for a in ch.get("articles", [])]
    today_urls = [a.get("link", "") for a in today_articles]
    if len(today_urls) != 140 or len(set(today_urls)) != 140:
        errors.append(f"today.json must contain 140 unique article URLs; count={len(today_urls)} unique={len(set(today_urls))}")

    bundle_rows: list[dict[str, Any]] = []
    for name in EXPECTED_FILES:
        try:
            rows = json.loads((data_dir / name).read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{name}: invalid JSON: {exc}")
            continue
        if not isinstance(rows, list) or len(rows) != 28:
            errors.append(f"{name}: expected list of 28 stories; found {len(rows) if isinstance(rows, list) else type(rows).__name__}")
            continue
        bundle_rows.extend(rows)

    bundle_urls = [r.get("url", "") for r in bundle_rows]
    if len(bundle_urls) != 140 or len(set(bundle_urls)) != 140:
        errors.append(f"story bundles must contain 140 unique URLs; count={len(bundle_urls)} unique={len(set(bundle_urls))}")
    if set(bundle_urls) != set(today_urls):
        errors.append("story bundle URL set does not exactly match today.json chapter article URL set")

    for row in bundle_rows:
        u = row.get("url", "")
        host = urlparse(u).netloc.lower()
        if not u.startswith(("http://", "https://")):
            errors.append(f"non-absolute story URL: {u}")
        if host.endswith("news.google.com"):
            errors.append(f"Google News relay URL is not an exact final article URL: {u}")
        if not row.get("freshness_note"):
            errors.append(f"missing freshness_note: {row.get('title','')}")
    return errors


def main() -> int:
    errors = validate_story_bundles()
    if errors:
        print("STORY_BUNDLE_GATE=FAIL")
        for e in errors:
            print(" -", e)
        return 2
    print("STORY_BUNDLE_GATE=PASS files=5 records=140 unique_urls=140")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
