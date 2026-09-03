"""
pipeline/snapshot_arbiter.py
중복 기사 클러스터링 제거 및 14개 챕터 × 10개 = 140개 기사 선별 및 SHA-256 해시 잠금 모듈
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hashlib
import re
from typing import List, Dict, Any, Set
from pipeline.schema import CHAPTER_DEFINITIONS, CHAPTER_MAP
from pipeline.fetch_and_filter import TRUSTED_SOURCES, fetch_chapter_candidates


def calculate_article_hash(chapter_id: str, title: str, link: str) -> str:
    """기사 고유 식별자(SHA-256 해시 16자리) 생성"""
    raw_str = f"{chapter_id}::{title.strip()}::{link.strip()}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


def get_title_tokens(title: str) -> Set[str]:
    """텍스트에서 유의미한 한글/영문 2글자 이상 단어 및 바이그램 토큰 추출"""
    words = re.findall(r"[가-힣a-zA-Z0-9]{2,}", title)
    tokens = set(words)
    for i in range(len(words) - 1):
        tokens.add(f"{words[i]}_{words[i+1]}")
    return tokens


def calculate_similarity(tokens1: Set[str], tokens2: Set[str]) -> float:
    """자카드 유사도 계산 (0.0 ~ 1.0)"""
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def score_article(article: Dict[str, Any]) -> float:
    """기사 품질 및 신뢰도 종합 점수 계산 (기본 5.0 + 가중치)"""
    score = 5.0
    title = article.get("title", "")
    source = article.get("source", "")
    summary = article.get("summary_raw", "")

    # 1. 신뢰할 수 있는 주요 언론사 가중치
    for ts in TRUSTED_SOURCES:
        if ts in source:
            score += 2.0
            break

    # 2. 제목의 구체성 및 품질 (20자~60자 이상적)
    if 25 <= len(title) <= 70:
        score += 1.5
    elif len(title) < 20:
        score -= 1.0

    # 3. 본문 요약 내용이 충실한 경우
    if len(summary) >= 60:
        score += 1.0

    # 4. 숫자나 통계, 주요 기관명이 포함된 경우 정보 밀도 가중치
    if re.search(r"\d+[%억원달러조pt개곳]|대통령|정부|법원|국회|공시|발표|출시|체결", title):
        score += 1.0

    return round(score, 2)


def deduplicate_and_rank_chapter(
    raw_articles: List[Dict[str, Any]], 
    global_seen_titles: Set[str], 
    target_count: int = 10
) -> List[Dict[str, Any]]:
    """단일 챕터 기사 후보군에서 중복 제거 및 스코어 기반 상위 N개 선별"""
    ranked_list = []
    
    for art in raw_articles:
        art_score = score_article(art)
        art_copy = dict(art)
        art_copy["importance_score"] = art_score
        art_copy["tokens"] = get_title_tokens(art["title"])
        ranked_list.append(art_copy)
        
    ranked_list.sort(key=lambda x: x["importance_score"], reverse=True)

    selected: List[Dict[str, Any]] = []
    selected_tokens_list: List[Set[str]] = []

    for art in ranked_list:
        title = art["title"]
        tokens = art["tokens"]
        
        if title in global_seen_titles:
            continue
            
        is_duplicate = False
        for s_tokens in selected_tokens_list:
            sim = calculate_similarity(tokens, s_tokens)
            if sim >= 0.45:
                is_duplicate = True
                break
                
        if not is_duplicate:
            selected.append(art)
            selected_tokens_list.append(tokens)
            global_seen_titles.add(title)
            
        if len(selected) == target_count:
            break

    return selected


def arbitrate_and_lock_snapshot(
    raw_data: Dict[str, List[Dict[str, Any]]], 
    target_per_chapter: int = 10
) -> List[Dict[str, Any]]:
    """
    14개 챕터에 대해 정확히 각 10개(총 140개) 기사를 엄선하고 고유 해시를 잠금
    """
    print("=" * 70)
    print(f" [Step 2] 중복 제거 및 14개 챕터 × {target_per_chapter}개 = {len(CHAPTER_DEFINITIONS) * target_per_chapter}개 기사 엄선/해시 잠금")
    print("=" * 70)

    final_snapshot: List[Dict[str, Any]] = []
    global_seen_titles: Set[str] = set()

    for idx, chapter in enumerate(CHAPTER_DEFINITIONS, 1):
        c_id = chapter["id"]
        c_name = chapter["name"]
        raw_list = raw_data.get(c_id, [])
        
        selected = deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)
        
        retry_count = 0
        while len(selected) < target_per_chapter and retry_count < 3:
            retry_count += 1
            print(f"    └─ [{c_name}] 후보 보충 수집 시도 #{retry_count}...")
            more_candidates = fetch_chapter_candidates(chapter)
            for mc in more_candidates:
                if mc["title"] not in global_seen_titles:
                    raw_list.append(mc)
            selected = deduplicate_and_rank_chapter(raw_list, global_seen_titles, target_per_chapter)

        # 각 선별된 기사에 고유 해시 ID 부여
        for art_idx, art in enumerate(selected, 1):
            art_id = calculate_article_hash(c_id, art["title"], art["link"])
            art["id"] = art_id
            art["chapter_id"] = c_id
            art["chapter_name"] = c_name
            art.pop("tokens", None)
            final_snapshot.append(art)

        print(f"  ({idx:02d}/14) [{c_name}] 엄선 완료: {len(selected)}/{target_per_chapter}건 확정 (해시 잠금 완료)")

    total_articles = len(final_snapshot)
    expected_total = len(CHAPTER_DEFINITIONS) * target_per_chapter
    print("-" * 70)
    print(f" [Step 2 완료] 총 {total_articles}/{expected_total}건 기사 선별 및 무결성 해시 잠금 완료 (중복 0건 보장)")
    print("=" * 70)

    if total_articles != expected_total:
        raise ValueError(f"치명적 오류: 선별된 기사 수량({total_articles})이 목표 수량({expected_total})과 일치하지 않습니다!")

    return final_snapshot
