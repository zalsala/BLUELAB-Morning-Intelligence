"""
pipeline/snapshot_arbiter.py
중복 제거, 최신성, 출처 다양성을 적용해 14개 챕터 × 10개 기사를 잠근다.
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Set

from pipeline.schema import CHAPTER_DEFINITIONS
from pipeline.fetch_and_filter import TRUSTED_SOURCES, fetch_chapter_candidates

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_AGE_DAYS = 3
MAX_PER_PUBLISHER = 2
MIN_UNIQUE_PUBLISHERS = 5


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
    current = now or datetime.now(timezone.utc)
    return (current - published).total_seconds() / 86400


def score_article(article: Dict[str, Any]) -> float:
    score = 5.0
    title = article.get("title", "")
    source = article.get("source", "")
    summary = article.get("summary_raw", "")
    age = article_age_days(article)

    for ts in TRUSTED_SOURCES:
        if ts in source:
            score += 2.0
            break
    if 25 <= len(title) <= 70:
        score += 1.5
    elif len(title) < 20:
        score -= 1.0
    if len(summary) >= 60:
        score += 1.0
    if re.search(r"\d+[%억원달러조pt개곳]|대통령|정부|법원|국회|공시|발표|출시|체결", title):
        score += 1.0
    # 최신 기사 우선. 24시간 이내 +2, 48시간 +1, 72시간 이내 +0.25.
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
    out=[]
    for art in raw_articles:
        age=article_age_days(art, now)
        if age is None:
            continue
        if age < -0.25 or age > MAX_AGE_DAYS:
            continue
        out.append(art)
    return out


def deduplicate_and_rank_chapter(raw_articles: List[Dict[str, Any]], global_seen_titles: Set[str], target_count: int = 10) -> List[Dict[str, Any]]:
    ranked_list=[]
    for art in _fresh_articles(raw_articles):
        art_copy=dict(art)
        art_copy["importance_score"]=score_article(art)
        art_copy["tokens"]=get_title_tokens(art["title"])
        ranked_list.append(art_copy)
    ranked_list.sort(key=lambda x:x["importance_score"], reverse=True)

    selected=[]
    selected_tokens=[]
    publisher_counts=Counter()
    for art in ranked_list:
        title=art["title"]
        source=(art.get("source") or "미상").strip()
        tokens=art["tokens"]
        if title in global_seen_titles or publisher_counts[source] >= MAX_PER_PUBLISHER:
            continue
        if any(calculate_similarity(tokens,s)>=0.45 for s in selected_tokens):
            continue
        selected.append(art)
        selected_tokens.append(tokens)
        publisher_counts[source]+=1
        global_seen_titles.add(title)
        if len(selected)==target_count:
            break

    if len(selected)==target_count and len(publisher_counts) < MIN_UNIQUE_PUBLISHERS:
        return []
    return selected


def arbitrate_and_lock_snapshot(raw_data: Dict[str,List[Dict[str,Any]]], target_per_chapter:int=10) -> List[Dict[str,Any]]:
    print("="*70)
    print(f" [Step 2] 최신성·중복·출처 다양성 적용: 14개 챕터 × {target_per_chapter}개")
    print("="*70)
    final_snapshot=[]
    global_seen_titles:set[str]=set()

    for idx,chapter in enumerate(CHAPTER_DEFINITIONS,1):
        c_id=chapter["id"]; c_name=chapter["name"]
        raw_list=list(raw_data.get(c_id,[]))
        selected=deduplicate_and_rank_chapter(raw_list,global_seen_titles,target_per_chapter)
        retry_count=0
        while len(selected)<target_per_chapter and retry_count<3:
            retry_count+=1
            print(f"    └─ [{c_name}] 최신·다양성 후보 보충 #{retry_count}...")
            raw_list.extend(fetch_chapter_candidates(chapter))
            # failed attempt may have populated global_seen_titles; rebuild only from prior chapters
            prior_titles={x["title"] for x in final_snapshot}
            global_seen_titles=set(prior_titles)
            selected=deduplicate_and_rank_chapter(raw_list,global_seen_titles,target_per_chapter)

        if len(selected)!=target_per_chapter:
            raise ValueError(f"{c_name}: freshness/diversity 기준을 만족하는 기사 {target_per_chapter}개를 확보하지 못했습니다 ({len(selected)}개)")

        pubs=Counter((a.get("source") or "미상").strip() for a in selected)
        for art in selected:
            art["id"]=calculate_article_hash(c_id,art["title"],art["link"])
            art["chapter_id"]=c_id; art["chapter_name"]=c_name
            art.pop("tokens",None)
            final_snapshot.append(art)
        print(f"  ({idx:02d}/14) [{c_name}] {len(selected)}/10 확정 / publishers={len(pubs)} / max_share={max(pubs.values()) if pubs else 0}")

    expected=len(CHAPTER_DEFINITIONS)*target_per_chapter
    if len(final_snapshot)!=expected:
        raise ValueError(f"선별 기사 수 {len(final_snapshot)} != {expected}")
    print(f" [Step 2 완료] {len(final_snapshot)}/{expected}건 freshness/diversity 잠금 PASS")
    return final_snapshot
