"""Evidence-aware editorial generation for production briefings.

P1 goals:
- keep Fact grounded in the selected article/evidence instead of generic filler;
- strip Google News-style concatenated headline/source noise from summaries;
- avoid Korean particle placeholders such as ``을(를)``;
- make Background / Why it matters / Checkpoints article-specific while retaining
  chapter context as a secondary frame.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from pipeline.editorial_builder import CHAPTER_INSIGHTS, extract_keywords
from pipeline.schema import Article, EditorialContent

_NOISE_DOMAINS = ("news.google.com", "v.daum.net")
_SENTENCE_END = re.compile(r"(?<=[.!?다요])\s+")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip(" -·|,")


def _source_with_particle(source: str) -> str:
    """Return a natural Korean source phrase without ambiguous 을(를)."""
    source = _normalize(source) or "주요 언론"
    return f"{source} 등 주요 매체"


def _looks_like_noise(fragment: str, title: str, source: str) -> bool:
    f = fragment.lower()
    if not fragment or fragment == title or fragment == source:
        return True
    if any(domain in f for domain in _NOISE_DOMAINS):
        return True
    if re.fullmatch(r"(?:연합뉴스|뉴스|종합|속보|단독|머니투데이|한국경제|경향신문|전자신문)", fragment):
        return True
    return False


def _summary_candidates(summary: str, title: str, source: str) -> List[str]:
    """Extract usable factual clauses from noisy aggregator/RSS summary text."""
    text = _normalize(summary)
    if not text:
        return []
    text = text.replace(title, " ").replace(source, " ")
    # Aggregated snippets frequently concatenate independent headlines. Prefer a
    # bounded first clause and reject fragments containing relay-domain markers.
    pieces = re.split(r"\s{2,}|\s+[|/]\s+|(?<=[.!?])\s+|\s+(?=\[[^\]]{1,30}\])", text)
    candidates: List[str] = []
    for piece in pieces:
        piece = _normalize(re.sub(r"\[[^\]]{1,30}\]", " ", piece))
        if len(piece) < 12 or _looks_like_noise(piece, title, source):
            continue
        # A relay/domain marker anywhere makes the whole fragment unsafe as Fact.
        if any(domain in piece.lower() for domain in _NOISE_DOMAINS):
            continue
        candidates.append(piece[:240].rstrip(" ,;"))
    return candidates


def _fact_text(raw: Dict[str, Any]) -> str:
    title = _normalize(raw.get("title", ""))
    source = _normalize(raw.get("source", "")) or "주요 언론"
    candidates = _summary_candidates(raw.get("summary_raw", ""), title, source)
    if candidates:
        clause = candidates[0]
        if clause.endswith(("다", "요", ".", "!", "?")):
            return f"{source} 보도에 따르면, {clause}"
        return f"{source} 보도에 따르면, {clause}로 전해졌습니다."
    # The headline itself is selected-source evidence. Do not invent facts that
    # are absent from the available source payload.
    return f"{source}는 ‘{title}’라고 보도했습니다. 세부 수치는 원문과 추가 근거에서 확인해야 합니다."


def _event_focus(title: str, keywords: List[str]) -> str:
    cleaned = re.sub(r"^\s*\[[^\]]+\]\s*", "", _normalize(title))
    if cleaned:
        return cleaned[:90]
    return "·".join(keywords[:2]) or "해당 사안"


def build_editorial_for_article_v2(raw: Dict[str, Any]) -> EditorialContent:
    chapter_id = raw.get("chapter_id", "top-headlines")
    title = _normalize(raw.get("title", ""))
    source = _normalize(raw.get("source", "")) or "주요 언론"
    summary = _normalize(raw.get("summary_raw", ""))
    insight = CHAPTER_INSIGHTS.get(chapter_id, CHAPTER_INSIGHTS["top-headlines"])
    keywords = extract_keywords(title, summary, chapter_id)
    focus = _event_focus(title, keywords)

    fact = _fact_text(raw)
    background = (
        f"‘{focus}’ 이슈는 {insight['bg']} "
        f"현재 {_source_with_particle(source)}의 보도를 통해 구체적인 전개가 확인되고 있습니다."
    )
    why = (
        f"이 사안의 핵심은 {', '.join(keywords[:3])}의 변화가 후속 정책·산업 의사결정에 미칠 영향입니다. "
        f"{insight['why']}"
    )

    fact_check = raw.get("fact_check") or {}
    evidence_urls = fact_check.get("evidence_urls") or []
    evidence_domains = []
    for url in evidence_urls:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        if domain and domain not in evidence_domains:
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
        keywords = extract_keywords(art["title"], art.get("summary_raw", ""), art["chapter_id"])
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
