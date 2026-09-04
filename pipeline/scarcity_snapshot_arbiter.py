"""Scarcity-first cross-chapter allocation wrapper with topical relevance."""
from __future__ import annotations

import urllib.parse
from collections import Counter
from typing import Any, Dict, List

from pipeline.schema import CHAPTER_DEFINITIONS
from pipeline.fetch_and_filter import fetch_chapter_candidates, fetch_rss_feed
from pipeline import snapshot_arbiter as base


EXTRA_FRESHNESS_QUERIES = {
    "realestate-construction": [
        "서울 아파트", "수도권 아파트", "부동산 정책", "주택 공급",
        "재건축 재개발", "아파트 분양 청약", "부동산 PF 건설", "국토교통부 주택",
    ]
}


def _stamp_chapter(rows: List[Dict[str, Any]], chapter: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["chapter_id"] = chapter["id"]
        item["chapter_name"] = chapter["name"]
        out.append(item)
    return out


def _freshness_queries(chapter: Dict[str, Any]) -> List[str]:
    base_queries = list(chapter.get("queries", []))
    base_queries.extend(EXTRA_FRESHNESS_QUERIES.get(chapter["id"], []))
    seen = set()
    out = []
    for q in base_queries:
        q = (q or "").strip()
        if not q:
            continue
        fresh_q = q if "when:" in q else f"{q} when:3d"
        if fresh_q not in seen:
            seen.add(fresh_q)
            out.append(fresh_q)
    return out


def _freshness_rescue(chapter: Dict[str, Any]) -> List[Dict[str, Any]]:
    queries = _freshness_queries(chapter)
    out: List[Dict[str, Any]] = []
    seen = set()
    for query in queries:
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        for item in fetch_rss_feed(url):
            key = item.get("link")
            if not key or key in seen:
                continue
            seen.add(key)
            row = dict(item)
            row["chapter_id"] = chapter["id"]
            row["chapter_name"] = chapter["name"]
            out.append(row)
    print(f"    └─ [{chapter['name']}] when:3d freshness rescue collected={len(out)} fresh={len(base._fresh_articles(out))}")
    return out


def _prepared_raw(chapter: Dict[str, Any], raw_data: Dict[str, List[Dict[str, Any]]], target_count: int = 10) -> List[Dict[str, Any]]:
    raw = _stamp_chapter(list(raw_data.get(chapter["id"], [])), chapter)
    if len(base._fresh_articles(raw)) < target_count:
        raw.extend(_freshness_rescue(chapter))
    return raw


def _scarcity_key(chapter: Dict[str, Any], prepared: Dict[str, List[Dict[str, Any]]]) -> tuple[int, int]:
    raw = prepared[chapter["id"]]
    fresh = base._fresh_articles(raw)
    unique_titles = {a.get("title", "").strip() for a in fresh if a.get("title")}
    canonical_index = next(i for i, c in enumerate(CHAPTER_DEFINITIONS) if c["id"] == chapter["id"])
    return (len(unique_titles), canonical_index)


def arbitrate_and_lock_snapshot(raw_data: Dict[str, List[Dict[str, Any]]], target_per_chapter: int = 10) -> List[Dict[str, Any]]:
    print("=" * 70)
    print(f" [Step 2] scarcity-first 최신성·관련성·중복·출처 다양성 적용: 14개 챕터 × {target_per_chapter}개")
    print("=" * 70)

    prepared = {c["id"]: _prepared_raw(c, raw_data, target_per_chapter) for c in CHAPTER_DEFINITIONS}
    allocation_order = sorted(CHAPTER_DEFINITIONS, key=lambda c: _scarcity_key(c, prepared))
    print(" [Allocation order] " + " -> ".join(c["name"] for c in allocation_order))

    global_seen_titles: set[str] = set()
    selected_by_chapter: Dict[str, List[Dict[str, Any]]] = {}

    for chapter in allocation_order:
        c_id = chapter["id"]
        c_name = chapter["name"]
        raw_list = list(prepared[c_id])
        selected = base.deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)
        retry_count = 0
        while len(selected) < target_per_chapter and retry_count < 3:
            retry_count += 1
            print(f"    └─ [{c_name}] 최신·관련성·다양성 후보 보충 #{retry_count}...")
            raw_list.extend(_stamp_chapter(fetch_chapter_candidates(chapter), chapter))
            raw_list.extend(_freshness_rescue(chapter))
            selected = base.deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)

        if len(selected) != target_per_chapter:
            fresh = base._fresh_articles(raw_list)
            fresh_count = len(fresh)
            unique_fresh = len({a.get('title','').strip() for a in fresh if a.get('title')})
            relevant_fresh = sum(1 for a in fresh if base.chapter_relevance(a, c_id)["passed"])
            raise ValueError(
                f"{c_name}: freshness/relevance/diversity 기준을 만족하는 기사 {target_per_chapter}개 확보 실패 "
                f"({len(selected)}개; fresh={fresh_count}; relevant_fresh={relevant_fresh}; "
                f"unique_fresh={unique_fresh}; globally_reserved={len(global_seen_titles)})"
            )

        pubs = Counter((a.get("source") or "미상").strip() for a in selected)
        if len(pubs) < base.MIN_UNIQUE_PUBLISHERS or max(pubs.values()) > base.MAX_PER_PUBLISHER:
            raise ValueError(f"{c_name}: publisher diversity gate failed ({dict(pubs)})")

        global_seen_titles.update(a["title"] for a in selected)
        selected_by_chapter[c_id] = selected
        print(f"  [ALLOC] [{c_name}] {len(selected)}/{target_per_chapter} / publishers={len(pubs)} / max_per_publisher={max(pubs.values())}")

    final_snapshot: List[Dict[str, Any]] = []
    for idx, chapter in enumerate(CHAPTER_DEFINITIONS, 1):
        c_id = chapter["id"]
        c_name = chapter["name"]
        selected = selected_by_chapter[c_id]
        for art in selected:
            item = dict(art)
            item["chapter_id"] = c_id
            item["chapter_name"] = c_name
            item.pop("tokens", None)
            final_snapshot.append(item)
        print(f"  ({idx:02d}/14) [{c_name}] {len(selected)}/{target_per_chapter}")

    expected = len(CHAPTER_DEFINITIONS) * target_per_chapter
    if len(final_snapshot) != expected:
        raise ValueError(f"선별 기사 수 {len(final_snapshot)} != {expected}")

    final_snapshot = base.resolve_exact_links(final_snapshot)
    seen_urls = set()
    for art in final_snapshot:
        if art["link"] in seen_urls:
            raise ValueError(f"exact URL cross-chapter duplicate: {art['link']}")
        seen_urls.add(art["link"])
        art["id"] = base.calculate_article_hash(art["chapter_id"], art["title"], art["link"])

    print(f" [Step 2 완료] {len(final_snapshot)}/{expected}건 scarcity/freshness/relevance/diversity/exact-url 잠금 PASS")
    return final_snapshot
