"""Evidence-aware editorial generation for production briefings.

P1 goals:
- keep Fact grounded in the selected article/evidence instead of generic filler;
- strip aggregator/RSS concatenated headline noise from summaries;
- avoid Korean particle placeholders such as ``을(를)``;
- make Background / Why it matters / Checkpoints article-specific while retaining
  chapter context as a secondary frame;
- fail closed to the selected headline when a summary clause cannot be tied to the
  same event with strong informative-token coverage;
- reject any candidate Fact clause that still contains another publisher marker;
- render human-readable publisher labels rather than relay/domain hostnames;
- never force a headline-like noun fragment into an invented Korean sentence ending.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from pipeline.content_quality import informative_title_tokens
from pipeline.editorial_builder import CHAPTER_INSIGHTS, extract_keywords
from pipeline.schema import Article, EditorialContent

_NOISE_DOMAINS = ("news.google.com", "v.daum.net", "news.nate.com")
_AGGREGATOR_SOURCE_LABELS = ("v.daum.net", "news.nate.com", "news.google.com", "네이트", "다음", "daum")
_DOMAIN_SOURCE_NAMES = {
    "yna.co.kr": "연합뉴스",
    "fnnews.com": "파이낸셜뉴스",
    "etnews.com": "전자신문",
    "hankyung.com": "한국경제",
    "chosun.com": "조선일보",
    "donga.com": "동아일보",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "newsis.com": "뉴시스",
    "mt.co.kr": "머니투데이",
    "sedaily.com": "서울경제",
    "edaily.co.kr": "이데일리",
}
_PUBLISHER_MARKERS = (
    "연합뉴스", "연합뉴스tv", "연합인포맥스", "뉴시스", "뉴스1", "한국경제", "머니투데이", "한겨레",
    "경향신문", "전자신문", "조선일보", "조선비즈", "chosunbiz", "중앙일보", "동아일보", "한국일보",
    "문화일보", "아시아경제", "서울경제", "서울신문", "매일경제", "이데일리", "헤럴드경제", "파이낸셜뉴스",
    "지디넷코리아", "etnews", "jtbc", "ytn", "mbc", "sbs", "kbs", "마켓인", "뉴스핌", "데일리안",
    "국민일보", "세계일보", "노컷뉴스", "오마이뉴스", "프레시안", "시사저널", "블로터",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip(" -·|,")


def _without_headline_tags(text: str) -> str:
    return _normalize(re.sub(r"^\s*(?:\[[^\]]{1,30}\]\s*)+", "", text or ""))


def _editorial_source(source: str) -> str:
    source = _normalize(source) or "주요 언론"
    low = source.lower().removeprefix("www.")
    if any(label in low for label in _AGGREGATOR_SOURCE_LABELS):
        return "원문 매체"
    if low in _DOMAIN_SOURCE_NAMES:
        return _DOMAIN_SOURCE_NAMES[low]
    if re.fullmatch(r"[a-z0-9.-]+\.(?:com|co\.kr|kr|net|org)", low):
        return "원문 매체"
    return source


def _source_with_particle(source: str) -> str:
    return f"{_editorial_source(source)} 등 주요 매체"


def _looks_like_noise(fragment: str, title: str, source: str) -> bool:
    f = fragment.lower()
    if not fragment or fragment == title or fragment == source:
        return True
    if any(domain in f for domain in _NOISE_DOMAINS):
        return True
    if re.search(r"\b(?:https?://|www\.)", f) or re.search(r"\b[a-z0-9.-]+\.(?:com|co\.kr|kr|net|org)\b", f):
        return True
    if re.fullmatch(r"(?:연합뉴스|뉴스|종합|속보|단독|머니투데이|한국경제|경향신문|전자신문)", fragment, re.I):
        return True
    return False


def _same_event_clause(fragment: str, title: str) -> bool:
    title_tokens = informative_title_tokens(title)
    frag_tokens = informative_title_tokens(fragment)
    if not title_tokens or not frag_tokens:
        return False
    shared = title_tokens & frag_tokens
    if len(shared) < 2:
        return False
    overlap = len(shared) / max(1, min(len(title_tokens), len(frag_tokens)))
    jaccard = len(shared) / max(1, len(title_tokens | frag_tokens))
    return overlap >= 0.50 and jaccard >= 0.25


def _publisher_hits(fragment: str, selected_source: str) -> List[str]:
    low = fragment.lower()
    selected = _editorial_source(selected_source).lower()
    hits: List[str] = []
    for marker in _PUBLISHER_MARKERS:
        m = marker.lower()
        if m in low and m not in selected and marker not in hits:
            hits.append(marker)
    return hits


def _strip_selected_title_and_source(piece: str, title: str, source: str) -> str:
    piece = _normalize(piece)
    clean_title = _without_headline_tags(title)
    clean_piece = _without_headline_tags(piece)
    if clean_title and clean_piece.startswith(clean_title):
        clean_piece = _normalize(clean_piece[len(clean_title):])
    source_forms = {_normalize(source), _editorial_source(source)}
    for form in sorted((f for f in source_forms if f), key=len, reverse=True):
        if clean_piece.startswith(form):
            clean_piece = _normalize(clean_piece[len(form):])
        if clean_piece.endswith(form):
            clean_piece = _normalize(clean_piece[:-len(form)])
    return clean_piece


def _summary_candidates(summary: str, title: str, source: str) -> List[str]:
    text = _normalize(summary)
    if not text:
        return []
    pieces = re.split(
        r"\s{2,}|\s+[|/]\s+|(?<=[.!?])\s+|\s+(?=\[[^\]]{1,30}\])",
        text,
    )
    candidates: List[str] = []
    for raw_piece in pieces:
        piece = _normalize(re.sub(r"\[[^\]]{1,30}\]", " ", raw_piece))
        piece = _strip_selected_title_and_source(piece, title, source)
        if len(piece) < 12 or _looks_like_noise(piece, title, source):
            continue
        low = piece.lower()
        if any(domain in low for domain in _NOISE_DOMAINS):
            continue
        if _publisher_hits(piece, source):
            continue
        if not _same_event_clause(piece, title):
            continue
        candidates.append(piece[:240].rstrip(" ,;"))
    return candidates


def _fallback_fact(source: str, title: str) -> str:
    return f"{source}는 ‘{title}’라고 보도했습니다. 세부 내용은 원문과 추가 근거에서 확인해야 합니다."


def _fact_text(raw: Dict[str, Any]) -> str:
    title = _normalize(raw.get("title", ""))
    raw_source = _normalize(raw.get("source", "")) or "주요 언론"
    source = _editorial_source(raw_source)
    candidates = _summary_candidates(raw.get("summary_raw", ""), title, raw_source)
    if candidates:
        clause = candidates[0]
        # Only reuse a summary clause when it already behaves like a complete
        # declarative sentence. A noun/headline fragment such as "최저치 경신"
        # must not become the ungrammatical fabricated ending "경신로 전해졌습니다".
        if clause.endswith(("다", "요", ".", "!", "?")):
            return f"{source} 보도에 따르면, {clause}"
        return _fallback_fact(source, title)
    return _fallback_fact(source, title)


def _event_focus(title: str, keywords: List[str]) -> str:
    cleaned = _without_headline_tags(title)
    if cleaned:
        return cleaned[:90]
    return "·".join(keywords[:2]) or "해당 사안"


def _clean_keywords(title: str, summary: str, chapter_id: str) -> List[str]:
    title_keywords = extract_keywords(title, "", chapter_id)
    useful = [k for k in title_keywords if k not in {"산업전망", "시장동향", "정책분석"}]
    if len(useful) >= 3:
        return useful[:4]
    combined = extract_keywords(title, summary, chapter_id)
    merged: List[str] = []
    for word in [*useful, *combined]:
        if word not in merged:
            merged.append(word)
    return merged[:4]


def build_editorial_for_article_v2(raw: Dict[str, Any]) -> EditorialContent:
    chapter_id = raw.get("chapter_id", "top-headlines")
    title = _normalize(raw.get("title", ""))
    raw_source = _normalize(raw.get("source", "")) or "주요 언론"
    source = _editorial_source(raw_source)
    summary = _normalize(raw.get("summary_raw", ""))
    insight = CHAPTER_INSIGHTS.get(chapter_id, CHAPTER_INSIGHTS["top-headlines"])
    keywords = _clean_keywords(title, summary, chapter_id)
    focus = _event_focus(title, keywords)

    fact = _fact_text(raw)
    background = (
        f"‘{focus}’ 이슈는 {insight['bg']} "
        f"현재 {_source_with_particle(source)}의 보도를 통해 구체적인 전개가 확인되고 있습니다."
    )
    focus_terms = ", ".join(keywords[:3]) or focus[:35]
    why = (
        f"이 사안은 {focus_terms}와 직접 연결돼 있어 후속 정책·산업 판단에 영향을 줄 수 있습니다. "
        f"{insight['why']}"
    )

    fact_check = raw.get("fact_check") or {}
    evidence_urls = fact_check.get("evidence_urls") or []
    evidence_domains: List[str] = []
    for url in evidence_urls:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        if not domain or any(noise == domain or domain.endswith("." + noise) for noise in _NOISE_DOMAINS):
            continue
        if domain not in evidence_domains:
            evidence_domains.append(domain)
    evidence_checkpoint = (
        f"독립 근거 도메인({', '.join(evidence_domains[:3])})의 후속 보도 일치 여부"
        if len(evidence_domains) >= 2
        else "독립된 두 번째 근거 또는 공식 1차 자료의 추가 확인"
    )
    checkpoints = [
        f"‘{focus[:55]}’ 관련 공식 발표·원문 업데이트",
        evidence_checkpoint,
        insight["points"][0],
    ]
    return EditorialContent(
        fact=fact,
        background=background,
        why_it_matters=why,
        checkpoints=checkpoints,
    )


def process_all_editorials(snapshot_articles: List[Dict[str, Any]]) -> List[Article]:
    print("=" * 70)
    print(" [Step 3] Evidence-aware Editorial Builder v2: Fact·배경·중요성·체크포인트")
    print("=" * 70)
    final_articles: List[Article] = []
    for idx, art in enumerate(snapshot_articles, 1):
        editorial = build_editorial_for_article_v2(art)
        keywords = _clean_keywords(art["title"], art.get("summary_raw", ""), art["chapter_id"])
        final_articles.append(Article(
            id=art["id"], chapter_id=art["chapter_id"], chapter_name=art["chapter_name"],
            title=art["title"], link=art["link"], source=art["source"],
            published_at=art.get("published_at", ""), summary_raw=art.get("summary_raw", ""),
            editorial=editorial, keywords=keywords,
            importance_score=art.get("importance_score", 5.0),
            fact_check=art.get("fact_check"), image=art.get("image"),
        ))
        if idx % 20 == 0 or idx == len(snapshot_articles):
            print(f"  └─ v2 에디토리얼 진행률: {idx}/{len(snapshot_articles)}")
    print(f" [Step 3 완료] {len(final_articles)}개 기사 evidence-aware editorial 생성 완료")
    print("=" * 70)
    return final_articles
