"""Deterministic Korean-language cleanup and validation for generated briefing text."""
from __future__ import annotations

import re
from typing import Iterable

from pipeline.korean_text import object_particle

_OBJECT_BEFORE_BIROTHAN = re.compile(r"('([^']+)')([을를])(?= 비롯한)")
_PLACEHOLDERS = ("을(를)", "이(가)", "은(는)")
_BAD_QUOTED_REPORT = "’이라는 내용이 전해졌습니다"
_ELLIPSIS_END = re.compile(r"(?:\.{2,}|…+)\s*$")
_REPORT_PREFIX = " 보도에 따르면, "


def polish_summary_line(line: str) -> str:
    """Correct the object particle after the quoted TOP5 headline."""
    def repl(match: re.Match[str]) -> str:
        quoted = match.group(1)
        headline = match.group(2)
        return f"{quoted}{object_particle(headline)}"

    return _OBJECT_BEFORE_BIROTHAN.sub(repl, line or "")


def polish_why_text(text: str) -> str:
    """Use particle-neutral wording for legacy generated keyword-focus sentences."""
    text = text or ""
    return text.replace("와 직접 연결돼 있어", "에 직접 연결돼 있어").replace(
        "과 직접 연결돼 있어", "에 직접 연결돼 있어"
    )


def polish_fact_text(text: str) -> str:
    """Normalize quoted-headline reporting to the particle-neutral '-라는 내용' form."""
    text = text or ""
    return text.replace(_BAD_QUOTED_REPORT, "’라는 내용이 전해졌습니다")


def _fact_has_incomplete_report_fragment(text: str) -> bool:
    """Detect summary-derived Fact clauses that visibly end in an ellipsis."""
    text = (text or "").strip()
    if _REPORT_PREFIX not in text:
        return False
    # Safe quoted-headline fallback includes a complete explanatory sentence;
    # validated body grounding uses '원문에 따르면' and is not handled here.
    if "’라는 내용이 전해졌습니다" in text or " 원문에 따르면, " in text:
        return False
    clause = text.split(_REPORT_PREFIX, 1)[1].strip()
    return bool(_ELLIPSIS_END.search(clause))


def _safe_headline_fallback(article: object) -> str:
    source = (getattr(article, "source", "") or "주요 언론").strip()
    title = (getattr(article, "title", "") or "").strip()
    return f"{source} 보도에 따르면, ‘{title}’라는 내용이 전해졌습니다. 세부 사실관계는 원문과 추가 근거에서 확인해야 합니다."


def polish_editorial_articles(articles: Iterable[object]) -> None:
    for article in articles:
        editorial = getattr(article, "editorial", None)
        if editorial is not None:
            editorial.fact = polish_fact_text(editorial.fact)
            if _fact_has_incomplete_report_fragment(editorial.fact):
                editorial.fact = _safe_headline_fallback(article)
            editorial.why_it_matters = polish_why_text(editorial.why_it_matters)


def polish_bundle_summary(bundle: object) -> None:
    bundle.three_line_summary = [polish_summary_line(line) for line in bundle.three_line_summary]


def validate_korean_quality(bundle: object) -> None:
    """Fail closed on known generated-language defects before publication."""
    texts = list(getattr(bundle, "three_line_summary", []) or [])
    fact_texts = []
    for chapter in getattr(bundle, "chapters", []) or []:
        for article in getattr(chapter, "articles", []) or []:
            editorial = getattr(article, "editorial", None)
            if editorial is None:
                continue
            fact_texts.append(editorial.fact)
            texts.extend([
                editorial.fact,
                editorial.background,
                editorial.why_it_matters,
                *editorial.checkpoints,
            ])

    errors = []
    for fact in fact_texts:
        if _fact_has_incomplete_report_fragment(fact):
            errors.append("incomplete fact clause ending in ellipsis")
    for text in texts:
        for placeholder in _PLACEHOLDERS:
            if placeholder in (text or ""):
                errors.append(f"ambiguous particle placeholder: {placeholder}")
        match = _OBJECT_BEFORE_BIROTHAN.search(text or "")
        if match and match.group(3) != object_particle(match.group(2)):
            errors.append(f"wrong object particle before 비롯한: {match.group(2)}{match.group(3)}")
        if "와 직접 연결돼 있어" in (text or "") or "과 직접 연결돼 있어" in (text or ""):
            errors.append("unpolished generated direct-connection particle")
        if _BAD_QUOTED_REPORT in (text or ""):
            errors.append("unnatural quoted-headline reporting particle")

    if errors:
        raise ValueError("Korean quality gate failed: " + " | ".join(errors[:10]))
