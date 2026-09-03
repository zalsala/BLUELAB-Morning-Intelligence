"""
pipeline/fetch_and_filter.py
구글 뉴스 및 주요 RSS 피드 수집과 광고/저품질 기사 필터링 모듈
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import html
import urllib.parse
from typing import List, Dict, Any, Optional
import feedparser
import requests
from bs4 import BeautifulSoup

from pipeline.schema import CHAPTER_DEFINITIONS, CHAPTER_MAP

# 차단할 광고/저품질 키워드 블랙리스트
BLACKLIST_TITLE_KEYWORDS = [
    "[인사]", "[부고]", "[동정]", "[포토]", "[화보]", "오늘의 운세", "띠별 운세",
    "포토뉴스", "이벤트", "할인 혜택", "특가 판매", "선착순 증정", "체험단 모집",
    "경품", "로또", "당첨번호", "비아그라", "카지노", "바카라", "토토"
]

# 신뢰도 높은 주요 언론사 가중치 목록
TRUSTED_SOURCES = [
    "연합뉴스", "한국경제", "매일경제", "조선일보", "중앙일보", "동아일보",
    "한겨레", "경향신문", "서울경제", "머니투데이", "이데일리", "뉴시스",
    "뉴스1", "전자신문", "디지털데일리", "지디넷코리아", "KBS", "MBC",
    "SBS", "YTN", "JTBC", "블로터", "더벨", "조선비즈", "동아사이언스"
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 BLUELAB-Morning-Intelligence/1.0"


def clean_html(raw_html: str) -> str:
    """HTML 태그 제거 및 텍스트 정제"""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    soup = BeautifulSoup(text, "html.parser")
    clean_text = soup.get_text(separator=" ", strip=True)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text


def extract_source_from_title(raw_title: str, entry_source: Optional[str] = None) -> tuple[str, str]:
    """구글 뉴스 제목에서 '기사 제목'과 '언론사명' 분리"""
    title = raw_title.strip()
    source = entry_source or "주요언론"
    
    if " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2 and len(parts[1].strip()) <= 20:
            title = parts[0].strip()
            source = parts[1].strip()
    
    return title, source


def is_quality_article(title: str, summary: str, source: str) -> bool:
    """광고, 저품질, 노이즈 기사 여부 판별"""
    if len(title) < 10 or len(title) > 120:
        return False
        
    for bl_word in BLACKLIST_TITLE_KEYWORDS:
        if bl_word in title:
            return False
            
    if title.count("…") > 3 or title.count("!") > 2 or title.count("?") > 2:
        return False
        
    clickbait_patterns = [r"경악", r"충격", r"알고보니 헉", r"발칵", r"숨진 채 발견\.\.\.충격"]
    for pat in clickbait_patterns:
        if re.search(pat, title):
            return False

    return True


def fetch_rss_feed(url: str, timeout: int = 10) -> List[Dict[str, Any]]:
    """단일 RSS URL 수집 및 엔트리 반환"""
    entries = []
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.content)
            for entry in feed.entries:
                raw_title = entry.get("title", "")
                link = entry.get("link", "")
                published = entry.get("published", entry.get("updated", ""))
                raw_summary = entry.get("summary", entry.get("description", ""))
                
                entry_source = None
                if hasattr(entry, "source") and isinstance(entry.source, dict):
                    entry_source = entry.source.get("title")
                    
                title, source = extract_source_from_title(raw_title, entry_source)
                clean_summary_text = clean_html(raw_summary)
                
                if not link or not title:
                    continue
                    
                if is_quality_article(title, clean_summary_text, source):
                    entries.append({
                        "title": title,
                        "link": link,
                        "source": source,
                        "published_at": published,
                        "summary_raw": clean_summary_text,
                    })
    except Exception as e:
        # print(f"  [경고] RSS 수집 실패 ({url}): {e}")
        pass
        
    return entries


def fetch_chapter_candidates(chapter_def: Dict[str, Any]) -> List[Dict[str, Any]]:
    """단일 챕터에 대한 뉴스 후보군 수집"""
    chapter_id = chapter_def["id"]
    chapter_name = chapter_def["name"]
    candidates: List[Dict[str, Any]] = []
    seen_urls = set()

    # 1. 구글 토픽 RSS 수집
    for topic_id in chapter_def.get("rss_topics", []):
        topic_url = f"https://news.google.com/rss/topics/{topic_id}?hl=ko&gl=KR&ceid=KR:ko"
        entries = fetch_rss_feed(topic_url)
        for e in entries:
            if e["link"] not in seen_urls:
                seen_urls.add(e["link"])
                e["chapter_id"] = chapter_id
                e["chapter_name"] = chapter_name
                candidates.append(e)

    # 2. 검색 쿼리 기반 RSS 수집
    queries = chapter_def.get("queries", [])
    for q in queries:
        encoded_query = urllib.parse.quote(q)
        search_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        entries = fetch_rss_feed(search_url)
        for e in entries:
            if e["link"] not in seen_urls:
                seen_urls.add(e["link"])
                e["chapter_id"] = chapter_id
                e["chapter_name"] = chapter_name
                candidates.append(e)
                
        if len(candidates) >= 30:
            break

    # 3. 만약 후보군이 부족한 경우 보조 쿼리 실행
    if len(candidates) < 15:
        fallback_queries = [f"{chapter_name} 뉴스", f"{chapter_name} 분석", "주요 뉴스"]
        for fq in fallback_queries:
            encoded_query = urllib.parse.quote(fq)
            search_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
            entries = fetch_rss_feed(search_url)
            for e in entries:
                if e["link"] not in seen_urls:
                    seen_urls.add(e["link"])
                    e["chapter_id"] = chapter_id
                    e["chapter_name"] = chapter_name
                    candidates.append(e)
            if len(candidates) >= 20:
                break

    return candidates


def fetch_all_chapters_raw() -> Dict[str, List[Dict[str, Any]]]:
    """14개 전 챕터에 대한 원시 기사 수집 및 필터링 실행"""
    print("=" * 70)
    print(" [Step 1] 14개 챕터별 실시간 RSS 뉴스 수집 및 품질 필터링 시작")
    print("=" * 70)
    
    all_raw_data: Dict[str, List[Dict[str, Any]]] = {}
    total_collected = 0

    for idx, chapter in enumerate(CHAPTER_DEFINITIONS, 1):
        c_id = chapter["id"]
        c_name = chapter["name"]
        print(f"  ({idx:02d}/14) [{c_name}] 뉴스 수집 중...", end=" ", flush=True)
        
        candidates = fetch_chapter_candidates(chapter)
        all_raw_data[c_id] = candidates
        total_collected += len(candidates)
        print(f"완료 (품질 통과 후보: {len(candidates)}건)")

    print("-" * 70)
    print(f" [Step 1 완료] 총 {len(CHAPTER_DEFINITIONS)}개 챕터에서 {total_collected}건의 고품질 기사 후보 수집 완료")
    print("=" * 70)
    return all_raw_data
