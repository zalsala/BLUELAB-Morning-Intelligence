"""Official Google Trends Korea RSS collector.
Publishes TOP20 only when exactly 20 unique reliable terms are available.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import feedparser
import requests

TRENDS_RSS = "https://trends.google.com/trending/rss?geo=KR"
TIMEOUT = 8


def _traffic(value: str) -> int:
    digits = re.sub(r"[^0-9]", "", value or "")
    return int(digits) if digits else 0


def collect_google_trends_kr() -> List[Dict[str, Any]]:
    try:
        r = requests.get(TRENDS_RSS, timeout=TIMEOUT, headers={"User-Agent":"BLUELAB-Morning-Intelligence/1.0"})
        r.raise_for_status()
        feed = feedparser.parse(r.content)
    except Exception as exc:
        print(f"  └─ Google Trends KR RSS unavailable: {type(exc).__name__}: {exc}")
        return []

    items=[]; seen=set()
    for entry in feed.entries:
        keyword=(entry.get("title") or "").strip()
        if not keyword or keyword.casefold() in seen:
            continue
        seen.add(keyword.casefold())
        traffic = entry.get("ht_approx_traffic") or entry.get("approx_traffic") or ""
        items.append({
            "keyword": keyword,
            "count": _traffic(traffic),
            "category": "Google Trends KR",
            "sentiment": "neutral",
            "source": "Google Trends",
            "source_url": TRENDS_RSS,
        })
        if len(items) == 20:
            break

    if len(items) != 20:
        print(f"  └─ Google Trends KR reliable terms={len(items)}; TOP20 hidden (requires exactly 20)")
        return []
    print("  └─ Google Trends KR official RSS: 20/20 PASS")
    return items
