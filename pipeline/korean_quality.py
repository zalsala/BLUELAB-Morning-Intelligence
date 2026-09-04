"""Deterministic Korean-language cleanup and validation for generated briefing text."""
from __future__ import annotations

import re
from typing import Iterable

from pipeline.korean_text import object_particle

_OBJECT_BEFORE_BIROTHAN = re.compile(r"('([^']+)')([을를])(?= 비롯한)")
_PLACEHOLDERS = ("을(를)", "이(가)", "은(는)")


def polish_summary_line(line: str) -> str:
    """Correct the object particle after the quoted TOP5 headline."""
    def repl(match: re.Match[str]) -> str:
        quoted = match.group(1)
        headline = match.group(2)
        return f"{quoted}{object_particle(headline)}"

    return _OBJECT_BEFORE_BIROTHAN.sub(repl, line or "")


def polish_why_text(text: str) -> str:
    """Use particle-neutral wording for the generated keyword-focus sentence."""
    text = text or ""
    return text.replace("와 직접 연결돼 있어", "에 직접 연결돼 있어").replace(
        "과 직접 연결돼 있어", "에 직접 연결돼 있어"
    )


def polish_editorial_articles(articles: Iterable[object]) -> None:
    for article in articles:
        editorial = getattr(article, "editorial", None)
        if editorial is not None:
            editorial.why_it_matters = polish_why_text(editorial.why_it_matters)


def polish_bundle_summary(bundle: object) -> None:
    bundle.three_line_summary = [polish_summary_line(line) for line in bundle.three_line_summary]


def validate_korean_quality(bundle: object) -> None:
    """Fail closed on known generated-particle defects before publication."""
    texts = list(getattr(bundle, "three_line_summary", []) or [])
    for chapter in getattr(bundle, "chapters", []) or []:
        for article in getattr(chapter, "articles", []) or []:
            editorial = getattr(article, "editorial", None)
            if editorial is None:
                continue
            texts.extend([
                editorial.fact,
                editorial.background,
                editorial.why_it_matters,
                *editorial.checkpoints,
            ])

    errors = []
    for text in texts:
        for placeholder in _PLACEHOLDERS:
            if placeholder in (text or ""):
                errors.append(f"ambiguous particle placeholder: {placeholder}")
        match = _OBJECT_BEFORE_BIROTHAN.search(text or "")
        if match and match.group(3) != object_particle(match.group(2)):
            errors.append(f"wrong object particle before 비롯한: {match.group(2)}{match.group(3)}")
        if "와 직접 연결돼 있어" in (text or "") or "과 직접 연결돼 있어" in (text or ""):
            errors.append("unpolished generated direct-connection particle")

    if errors:
        raise ValueError("Korean quality gate failed: " + " | ".join(errors[:10]))
