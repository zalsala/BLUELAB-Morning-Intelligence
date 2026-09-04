"""Content-quality helpers for chapter relevance and evidence handling.

P0 policy:
- Chapter relevance is title-first. Summary text is only supporting evidence.
- Generic discovery snippets must not outweigh a clearly off-topic title.
- VERIFIED_MULTI_SOURCE requires >=2 independent evidence domains.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set
from urllib.parse import urlparse


CHAPTER_RELEVANCE = {
    "politics-policy": {
        "positive": ["대통령", "대통령실", "국회", "정부", "정책", "법안", "여야", "장관", "규제", "행정", "선거", "정당"],
        "negative": ["게임", "DLC", "신작", "아이돌", "앨범", "영화"],
    },
    "macro-finance": {
        "positive": ["금리", "환율", "코스피", "코스닥", "증시", "채권", "물가", "경상수지", "무역수지", "금융", "은행", "대출", "GDP", "성장률", "원달러", "Fed", "FOMC"],
        "negative": ["게임", "DLC", "신작 게임", "아이돌", "콘서트", "영화"],
    },
    "global-affairs": {
        "positive": ["미국", "중국", "일본", "유럽", "EU", "러시아", "우크라이나", "이란", "이스라엘", "관세", "무역", "외교", "전쟁", "안보", "정상회담", "제재"],
        "negative": ["게임", "DLC", "아이돌", "드라마"],
    },
    "tech-it": {
        "positive": ["클라우드", "소프트웨어", "플랫폼", "사이버", "보안", "스마트폰", "아이폰", "안드로이드", "네이버", "카카오", "구글", "마이크로소프트", "애플", "IT", "데이터센터"],
        "negative": ["아파트", "주택", "청약", "부동산", "전세", "재건축"],
    },
    "ai-deeptech": {
        "positive": ["AI", "인공지능", "LLM", "GPT", "로봇", "로보틱스", "딥테크", "에이전트", "양자", "머신러닝", "생성형"],
        "negative": ["아파트", "청약", "전세", "아이돌"],
    },
    "semiconductors-mfg": {
        "positive": ["반도체", "HBM", "파운드리", "메모리", "D램", "낸드", "배터리", "이차전지", "디스플레이", "공정", "팹", "소재", "장비"],
        "negative": ["게임", "DLC", "아이돌", "아파트"],
    },
    "bio-healthcare": {
        "positive": ["바이오", "제약", "신약", "임상", "FDA", "의료", "병원", "헬스케어", "백신", "치료제", "의약품"],
        "negative": ["게임", "아파트", "아이돌"],
    },
    "energy-mobility": {
        "positive": ["전기차", "자동차", "테슬라", "현대차", "기아", "자율주행", "배터리", "원전", "SMR", "태양광", "풍력", "전력", "에너지", "수소", "UAM"],
        "negative": ["게임", "아이돌", "아파트 분양"],
    },
    "realestate-construction": {
        "positive": ["아파트", "주택", "부동산", "청약", "분양", "전세", "월세", "재건축", "재개발", "건설", "PF", "집값", "국토부", "토지"],
        "negative": ["게임", "DLC", "아이돌", "스마트폰"],
    },
    "retail-consumer": {
        "positive": ["유통", "소비", "소비자", "이커머스", "쿠팡", "백화점", "마트", "편의점", "식품", "K푸드", "뷰티", "패션", "물가"],
        "negative": ["전쟁", "반도체 공정", "임상 3상"],
    },
    "society-environment": {
        "positive": ["고용", "노동", "환경", "탄소", "기후", "저출산", "고령화", "사건", "사고", "법원", "교육", "학교", "사회", "복지", "인구"],
        "negative": ["게임 DLC", "HBM", "파운드리"],
    },
    "culture-entertainment": {
        "positive": ["K-POP", "아이돌", "가수", "음원", "앨범", "영화", "드라마", "OTT", "넷플릭스", "게임", "웹툰", "엔터", "공연", "콘서트"],
        "negative": ["금리", "환율", "아파트 청약", "반도체 공정"],
    },
    "science-future": {
        "positive": ["우주", "위성", "로켓", "누리호", "달탐사", "핵융합", "양자", "신소재", "과학", "연구", "천문", "물리", "생명과학", "연구진"],
        "negative": ["수입차 판매", "개인정보 유출", "아파트", "DLC", "아이돌"],
    },
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def chapter_relevance(article: Dict[str, Any], chapter_id: str) -> Dict[str, Any]:
    """Return a machine-readable relevance decision.

    Top headlines intentionally remain broad. For specialist chapters:
    - a negative title signal is a hard reject unless the title also contains a
      strong positive signal;
    - >=1 positive title hit passes;
    - otherwise >=2 distinct positive summary hits are required.
    """
    if chapter_id == "top-headlines":
        return {"passed": True, "score": 1.0, "title_hits": [], "summary_hits": [], "reason": "broad_chapter"}

    policy = CHAPTER_RELEVANCE.get(chapter_id)
    if not policy:
        return {"passed": False, "score": 0.0, "title_hits": [], "summary_hits": [], "reason": "missing_policy"}

    title = _norm(article.get("title", ""))
    summary = _norm(article.get("summary_raw", ""))
    positives = [_norm(x) for x in policy["positive"]]
    negatives = [_norm(x) for x in policy["negative"]]

    title_hits = sorted({p for p in positives if p and p in title})
    summary_hits = sorted({p for p in positives if p and p in summary})
    negative_hits = sorted({n for n in negatives if n and n in title})

    if negative_hits and not title_hits:
        return {
            "passed": False,
            "score": -1.0,
            "title_hits": title_hits,
            "summary_hits": summary_hits,
            "negative_hits": negative_hits,
            "reason": "negative_title_signal",
        }

    if title_hits:
        score = min(1.0, 0.65 + 0.1 * (len(title_hits) - 1) + 0.05 * min(len(summary_hits), 3))
        return {
            "passed": True,
            "score": round(score, 3),
            "title_hits": title_hits,
            "summary_hits": summary_hits,
            "negative_hits": negative_hits,
            "reason": "title_match",
        }

    if len(summary_hits) >= 2:
        return {
            "passed": True,
            "score": min(0.6, round(0.25 + 0.1 * len(summary_hits), 3)),
            "title_hits": title_hits,
            "summary_hits": summary_hits,
            "negative_hits": negative_hits,
            "reason": "summary_support",
        }

    return {
        "passed": False,
        "score": 0.0,
        "title_hits": title_hits,
        "summary_hits": summary_hits,
        "negative_hits": negative_hits,
        "reason": "insufficient_topic_evidence",
    }


def independent_evidence_urls(article: Dict[str, Any]) -> List[str]:
    """Return unique http(s) evidence URLs supplied by verification stages."""
    raw: List[str] = []
    for key in ("verification_evidence", "corroborating_urls", "evidence_urls"):
        value = article.get(key)
        if isinstance(value, str):
            raw.append(value)
        elif isinstance(value, Iterable) and not isinstance(value, (dict, bytes)):
            for item in value:
                if isinstance(item, str):
                    raw.append(item)
                elif isinstance(item, dict) and isinstance(item.get("url"), str):
                    raw.append(item["url"])

    out: List[str] = []
    seen_domains: Set[str] = set()
    for url in raw:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        domain = parsed.netloc.lower().removeprefix("www.")
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        out.append(url.strip())
    return out
