"""Deterministic evidence-weighted TOP5 ranking.

TOP5 is a prominence surface for factual news, not an opinion section. Ranking
combines editorial importance, chapter-level public impact, verification
quality, exact-body validation and recency, while excluding clearly labelled
editorials/columns and keeping chapter diversity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from typing import Iterable, List, Tuple

from pipeline.schema import Article

_CHAPTER_IMPACT = {
    "top-headlines": 1.3,
    "politics-policy": 1.2,
    "macro-finance": 1.4,
    "global-affairs": 1.35,
    "tech-it": 0.9,
    "ai-deeptech": 1.05,
    "semiconductors-mfg": 1.1,
    "bio-healthcare": 1.05,
    "energy-mobility": 1.0,
    "realestate-construction": 1.0,
    "retail-consumer": 0.85,
    "society-environment": 1.0,
    "culture-entertainment": 0.7,
    "science-future": 0.9,
}

_EVIDENCE_WEIGHT = {
    "VERIFIED_OFFICIAL": 2.0,
    "VERIFIED_PRIMARY": 1.8,
    "VERIFIED_MULTI_SOURCE": 1.6,
    "PARTIAL": -0.8,
    "UNVERIFIED": -2.5,
    "ACCESS_BLOCKED": -1.5,
    "CONFLICT": -3.0,
}

_BODY_WEIGHT = {
    "VALIDATED": 0.8,
    "EVENT_MISMATCH": -0.5,
    "NO_QUALIFIED_BODY": 0.0,
    "HTTP_403": 0.0,
    "HTTP_404": -0.2,
    "TIMEOUT": 0.0,
}

# Explicit opinion labels are disqualified from the factual TOP5 surface. This
# is intentionally conservative: an article can still remain in its chapter,
# but it cannot displace a factual news report in the headline ranking.
_OPINION_PREFIX_RE = re.compile(
    r"^\s*(?:\[(?:사설|칼럼|기고|시론|논설|오피니언|데스크칼럼|취재수첩|기자수첩)\]|"
    r"(?:사설|칼럼|기고|시론|논설|오피니언)\s*[:：])",
    re.IGNORECASE,
)


def is_top5_title_eligible(title: str) -> bool:
    """Return whether a raw title is eligible for the factual TOP5 surface."""
    normalized = (title or "").strip()
    if not normalized:
        return False
    return _OPINION_PREFIX_RE.search(normalized) is None


def is_top5_eligible(article: Article) -> bool:
    return is_top5_title_eligible(article.title)


def _recency_points(published_at: str, now: datetime | None = None) -> float:
    if not published_at:
        return 0.0
    now = now or datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(published_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hours = max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return 0.0
    if hours <= 6:
        return 1.0
    if hours <= 12:
        return 0.7
    if hours <= 24:
        return 0.4
    if hours <= 48:
        return 0.1
    return -0.4


def score_top5_candidate(article: Article, now: datetime | None = None) -> Tuple[float, dict]:
    fact = article.fact_check or {}
    status = fact.get("status", "UNVERIFIED")
    body_status = (fact.get("body_validation") or {}).get("status", "NO_QUALIFIED_BODY")
    base = float(article.importance_score or 0.0)
    impact = _CHAPTER_IMPACT.get(article.chapter_id, 0.5)
    evidence = _EVIDENCE_WEIGHT.get(status, -1.0)
    body = _BODY_WEIGHT.get(body_status, 0.0)
    recency = _recency_points(article.published_at, now)
    total = round(base + impact + evidence + body + recency, 4)
    return total, {
        "base": base,
        "chapter_impact": impact,
        "evidence": evidence,
        "body": body,
        "recency": recency,
        "fact_status": status,
        "body_status": body_status,
        "top5_eligible": is_top5_eligible(article),
    }


def select_top5_v2(articles: Iterable[Article], now: datetime | None = None) -> List[Article]:
    """Select five factual, high-impact articles with evidence and diversity.

    Rules:
    - explicitly labelled opinion/editorial pieces are ineligible for TOP5;
    - score eligible articles deterministically;
    - first pass allows at most one item per chapter;
    - PARTIAL articles remain eligible but pay an evidence penalty;
    - if fewer than five chapters are available, fill by score.
    """
    scored = []
    for art in articles:
        if not is_top5_eligible(art):
            continue
        score, detail = score_top5_candidate(art, now)
        scored.append((score, art.importance_score, art.id, art, detail))
    scored.sort(key=lambda row: (-row[0], -float(row[1] or 0), row[2]))

    selected: List[Article] = []
    seen_chapters = set()
    for _, _, _, art, _ in scored:
        if art.chapter_id in seen_chapters:
            continue
        selected.append(art)
        seen_chapters.add(art.chapter_id)
        if len(selected) == 5:
            return selected

    for _, _, _, art, _ in scored:
        if art not in selected:
            selected.append(art)
            if len(selected) == 5:
                break
    return selected
