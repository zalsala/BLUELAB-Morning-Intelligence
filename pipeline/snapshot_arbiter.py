"""
pipeline/snapshot_arbiter.py
중복 제거, 최신성, 출처 다양성, 챕터 관련성을 적용하고 Google News discovery URL을 원문으로 해석한 뒤
14개 챕터 × 10개 기사를 잠근다.
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

from googlenewsdecoder import gnewsdecoder
from pipeline.schema import CHAPTER_DEFINITIONS
from pipeline.fetch_and_filter import TRUSTED_SOURCES, fetch_chapter_candidates
from pipeline.content_quality import chapter_relevance

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_AGE_DAYS = 3
MAX_PER_PUBLISHER = 2
MIN_UNIQUE_PUBLISHERS = 5
DECODE_WORKERS = 6


def calculate_article_hash(chapter_id: str, title: str, link: str) -> str:
    raw_str = f"{chapter_id}::{title.strip()}::{link.strip()}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


def get_title_tokens(title: str) -> Set[str]:
    words = re.findall(r"[가-힣a-zA-Z0-9]{2,}", title)
    tokens = set(words)
    for i in range(len(words) - 1):
        tokens.add(f"{words[i]}_{words[i+1]}")
    return tokens


def calculate_similarity(tokens1: Set[str], tokens2: Set[str]) -> float:
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1 & tokens2) / len(tokens1 | tokens2)


def parse_published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        d = parsedate_to_datetime(value)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        except Exception:
            return None


def article_age_days(article: Dict[str, Any], now: datetime | None = None) -> float | None:
    published = parse_published(article.get("published_at", ""))
    if not published:
        return None
    return ((now or datetime.now(timezone.utc)) - published).total_seconds() / 86400


def score_article(article: Dict[str, Any]) -> float:
    score = 5.0
    title = article.get("title", "")
    source = article.get("source", "")
    summary = article.get("summary_raw", "")
    age = article_age_days(article)
    if any(ts in source for ts in TRUSTED_SOURCES):
        score += 2.0
    if 25 <= len(title) <= 70:
        score += 1.5
    elif len(title) < 20:
        score -= 1.0
    if len(summary) >= 60:
        score += 1.0
    if re.search(r"\d+[%억원달러조pt개곳]|대통령|정부|법원|국회|공시|발표|출시|체결", title):
        score += 1.0
    if age is not None:
        if age <= 1:
            score += 2.0
        elif age <= 2:
            score += 1.0
        elif age <= MAX_AGE_DAYS:
            score += 0.25
    return round(score, 2)


def _fresh_articles(raw_articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [a for a in raw_articles if (age := article_age_days(a, now)) is not None and -0.25 <= age <= MAX_AGE_DAYS]


def deduplicate_and_rank_chapter(raw_articles: List[Dict[str, Any]], prior_global_titles: Set[str], target_count: int = 10) -> List[Dict[str, Any]]:
    """선별 중에는 global state를 절대 변경하지 않는다. 완전한 10건 승인 후 caller가 commit한다."""
    ranked = []
    relevance_rejected = 0
    for art in _fresh_articles(raw_articles):
        chapter_id = art.get("chapter_id", "")
        relevance = chapter_relevance(art, chapter_id)
        if not relevance["passed"]:
            relevance_rejected += 1
            continue
        item = dict(art)
        item["importance_score"] = score_article(art) + relevance["score"]
        item["topic_relevance"] = relevance
        item["tokens"] = get_title_tokens(art["title"])
        ranked.append(item)

    if relevance_rejected:
        chapter_label = raw_articles[0].get("chapter_name", "") if raw_articles else ""
        print(f"    └─ [{chapter_label}] topical relevance rejected={relevance_rejected}")

    ranked.sort(key=lambda x: x["importance_score"], reverse=True)

    selected = []
    selected_tokens = []
    publisher_counts = Counter()
    for art in ranked:
        title = art["title"]
        source = (art.get("source") or "미상").strip()
        tokens = art["tokens"]
        if title in prior_global_titles or publisher_counts[source] >= MAX_PER_PUBLISHER:
            continue
        if any(calculate_similarity(tokens, s) >= 0.45 for s in selected_tokens):
            continue
        selected.append(art)
        selected_tokens.append(tokens)
        publisher_counts[source] += 1
        if len(selected) == target_count:
            break
    if len(selected) == target_count and len(publisher_counts) < MIN_UNIQUE_PUBLISHERS:
        return []
    return selected


def _decode_one(item: Dict[str, Any]) -> tuple[Dict[str, Any], str | None]:
    out = dict(item)
    link = out.get("link", "")
    if urlparse(link).netloc.lower() != "news.google.com":
        return out, None
    try:
        result = gnewsdecoder(link, interval=None)
        decoded = (result or {}).get("decoded_url") if (result or {}).get("status") else None
        if not decoded or urlparse(decoded).netloc.lower().endswith("news.google.com"):
            return out, (result or {}).get("message") or "decoder returned no exact URL"
        out["discovery_link"] = link
        out["link"] = decoded
        return out, None
    except Exception as exc:
        return out, f"{type(exc).__name__}: {exc}"


def resolve_exact_links(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    resolved = [None] * len(items)
    errors = []
    with ThreadPoolExecutor(max_workers=DECODE_WORKERS) as pool:
        futures = {pool.submit(_decode_one, item): i for i, item in enumerate(items)}
        for future in as_completed(futures):
            i = futures[future]
            item, error = future.result()
            resolved[i] = item
            if error:
                errors.append((item.get("chapter_name"), item.get("title"), error))
    if errors:
        print(f" [Exact URL] FAIL unresolved={len(errors)}")
        for chapter, title, error in errors[:10]:
            print(f"   - [{chapter}] {title}: {error}")
        raise ValueError(f"Google News discovery URL {len(errors)}건을 exact article URL로 승격하지 못했습니다")
    print(f" [Exact URL] PASS resolved={sum(1 for x in resolved if x.get('discovery_link'))} / total={len(resolved)}")
    return resolved


def arbitrate_and_lock_snapshot(raw_data: Dict[str, List[Dict[str, Any]]], target_per_chapter: int = 10) -> List[Dict[str, Any]]:
    print("=" * 70)
    print(f" [Step 2] 최신성·관련성·중복·출처 다양성 적용: 14개 챕터 × {target_per_chapter}개")
    print("=" * 70)
    final_snapshot = []
    global_seen_titles: set[str] = set()

    for idx, chapter in enumerate(CHAPTER_DEFINITIONS, 1):
        c_id = chapter["id"]
        c_name = chapter["name"]
        raw_list = []
        for raw in raw_data.get(c_id, []):
            item = dict(raw)
            item["chapter_id"] = c_id
            item["chapter_name"] = c_name
            raw_list.append(item)

        selected = deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)
        retry_count = 0
        while len(selected) < target_per_chapter and retry_count < 3:
            retry_count += 1
            print(f"    └─ [{c_name}] 최신·관련성·다양성 후보 보충 #{retry_count}...")
            fetched = fetch_chapter_candidates(chapter)
            for raw in fetched:
                item = dict(raw)
                item["chapter_id"] = c_id
                item["chapter_name"] = c_name
                raw_list.append(item)
            selected = deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)

        if len(selected) != target_per_chapter:
            raise ValueError(f"{c_name}: freshness/relevance/diversity 기준을 만족하는 기사 10개 확보 실패 ({len(selected)}개)")
        pubs = Counter((a.get("source") or "미상").strip() for a in selected)
        global_seen_titles.update(a["title"] for a in selected)
        for art in selected:
            art.pop("tokens", None)
            final_snapshot.append(art)
        print(f"  ({idx:02d}/14) [{c_name}] 10/10 / publishers={len(pubs)} / max_per_publisher={max(pubs.values())}")

    expected = len(CHAPTER_DEFINITIONS) * target_per_chapter
    if len(final_snapshot) != expected:
        raise ValueError(f"선별 기사 수 {len(final_snapshot)} != {expected}")

    final_snapshot = resolve_exact_links(final_snapshot)
    seen_urls = set()
    for art in final_snapshot:
        if art["link"] in seen_urls:
            raise ValueError(f"exact URL cross-chapter duplicate: {art['link']}")
        seen_urls.add(art["link"])
        art["id"] = calculate_article_hash(art["chapter_id"], art["title"], art["link"])
    print(f" [Step 2 완료] {len(final_snapshot)}/{expected}건 freshness/relevance/diversity/exact-url 잠금 PASS")
    return final_snapshot
