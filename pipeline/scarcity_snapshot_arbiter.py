"""
Scarcity-first cross-chapter allocation wrapper.

Keeps all existing freshness, publisher-diversity, event-similarity and exact-URL
quality gates from snapshot_arbiter, but removes canonical display-order bias by
allocating chapters with the fewest fresh unique candidate titles first.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from pipeline.schema import CHAPTER_DEFINITIONS
from pipeline.fetch_and_filter import fetch_chapter_candidates
from pipeline import snapshot_arbiter as base


def _scarcity_key(chapter: Dict[str, Any], raw_data: Dict[str, List[Dict[str, Any]]]) -> tuple[int, int]:
    raw = list(raw_data.get(chapter["id"], []))
    fresh = base._fresh_articles(raw)
    unique_titles = {a.get("title", "").strip() for a in fresh if a.get("title")}
    # Fewer usable titles first. Canonical index is a deterministic tie-breaker.
    canonical_index = next(i for i, c in enumerate(CHAPTER_DEFINITIONS) if c["id"] == chapter["id"])
    return (len(unique_titles), canonical_index)


def arbitrate_and_lock_snapshot(raw_data: Dict[str, List[Dict[str, Any]]], target_per_chapter: int = 10) -> List[Dict[str, Any]]:
    print("=" * 70)
    print(f" [Step 2] scarcity-first 최신성·중복·출처 다양성 적용: 14개 챕터 × {target_per_chapter}개")
    print("=" * 70)

    allocation_order = sorted(CHAPTER_DEFINITIONS, key=lambda c: _scarcity_key(c, raw_data))
    print(" [Allocation order] " + " -> ".join(c["name"] for c in allocation_order))

    global_seen_titles: set[str] = set()
    selected_by_chapter: Dict[str, List[Dict[str, Any]]] = {}

    for chapter in allocation_order:
        c_id = chapter["id"]
        c_name = chapter["name"]
        raw_list = list(raw_data.get(c_id, []))
        selected = base.deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)
        retry_count = 0
        while len(selected) < target_per_chapter and retry_count < 3:
            retry_count += 1
            print(f"    └─ [{c_name}] 최신·다양성 후보 보충 #{retry_count}...")
            raw_list.extend(fetch_chapter_candidates(chapter))
            selected = base.deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)

        if len(selected) != target_per_chapter:
            fresh_count = len(base._fresh_articles(raw_list))
            unique_fresh = len({a.get('title','').strip() for a in base._fresh_articles(raw_list) if a.get('title')})
            raise ValueError(
                f"{c_name}: freshness/diversity 기준을 만족하는 기사 {target_per_chapter}개 확보 실패 "
                f"({len(selected)}개; fresh={fresh_count}; unique_fresh={unique_fresh}; globally_reserved={len(global_seen_titles)})"
            )

        pubs = Counter((a.get("source") or "미상").strip() for a in selected)
        if len(pubs) < base.MIN_UNIQUE_PUBLISHERS or max(pubs.values()) > base.MAX_PER_PUBLISHER:
            raise ValueError(f"{c_name}: publisher diversity gate failed ({dict(pubs)})")

        global_seen_titles.update(a["title"] for a in selected)
        selected_by_chapter[c_id] = selected
        print(f"  [ALLOC] [{c_name}] {len(selected)}/{target_per_chapter} / publishers={len(pubs)} / max_per_publisher={max(pubs.values())}")

    # Restore canonical chapter display order after allocation.
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

    print(f" [Step 2 완료] {len(final_snapshot)}/{expected}건 scarcity/freshness/diversity/exact-url 잠금 PASS")
    return final_snapshot
