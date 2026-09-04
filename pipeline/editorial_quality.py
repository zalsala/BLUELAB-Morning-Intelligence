"""Evidence-aware editorial generation with deterministic Korean safety gates."""
from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from pipeline.content_quality import informative_title_tokens
from pipeline.editorial_builder import extract_keywords
from pipeline.schema import Article, EditorialContent

_NOISE_DOMAINS = ("news.google.com", "v.daum.net", "news.nate.com")
_AGGREGATOR_SOURCE_LABELS = ("v.daum.net", "news.nate.com", "news.google.com", "네이트", "다음", "daum")
_DOMAIN_SOURCE_NAMES = {
    "yna.co.kr": "연합뉴스", "fnnews.com": "파이낸셜뉴스", "etnews.com": "전자신문",
    "hankyung.com": "한국경제", "chosun.com": "조선일보", "donga.com": "동아일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문", "newsis.com": "뉴시스",
    "mt.co.kr": "머니투데이", "sedaily.com": "서울경제", "edaily.co.kr": "이데일리",
}
_PUBLISHER_MARKERS = (
    "연합뉴스", "연합뉴스tv", "연합인포맥스", "뉴시스", "뉴스1", "한국경제", "머니투데이", "한겨레",
    "경향신문", "전자신문", "조선일보", "조선비즈", "chosunbiz", "중앙일보", "동아일보", "한국일보",
    "문화일보", "아시아경제", "서울경제", "서울신문", "매일경제", "이데일리", "헤럴드경제", "파이낸셜뉴스",
    "지디넷코리아", "etnews", "jtbc", "ytn", "mbc", "sbs", "kbs", "마켓인", "뉴스핌", "데일리안",
    "국민일보", "세계일보", "노컷뉴스", "오마이뉴스", "프레시안", "시사저널", "블로터",
)

_CHAPTER_CONTEXT = {
    "top-headlines": (
        "국내외 주요 현안의 후속 사실관계와 공식 대응을 확인해야 하는 사안입니다.",
        "정책·여론·시장 반응이 어떻게 이어지는지 확인할 필요가 있습니다.",
        "정부·관계기관의 공식 후속 발표",
    ),
    "politics-policy": (
        "정책 결정과 입법·행정 절차의 후속 변화가 핵심입니다.",
        "실제 제도 변경 여부와 이해관계자 영향 범위를 확인할 필요가 있습니다.",
        "정부·국회·관계기관의 공식 절차와 후속 일정",
    ),
    "macro-finance": (
        "금리·환율·증시·유동성 등 금융 변수의 변화를 함께 봐야 하는 사안입니다.",
        "시장 가격과 자금 흐름에 미치는 실제 영향을 후속 지표로 확인할 필요가 있습니다.",
        "금리·환율·수급 등 핵심 시장지표의 후속 변화",
    ),
    "global-affairs": (
        "외교·안보·통상 환경의 변화와 당사국의 후속 대응을 함께 확인해야 하는 사안입니다.",
        "지역 안보와 국제관계에 미치는 영향은 공식 조치와 후속 협상에 따라 달라질 수 있습니다.",
        "당사국 정부와 국제기구의 공식 후속 조치",
    ),
    "tech-it": (
        "제품·플랫폼·규제·보안 등 기술 산업의 실제 변화 여부를 확인해야 하는 사안입니다.",
        "이용자·기업·생태계에 미치는 영향은 출시·도입·규제 집행 결과로 확인할 필요가 있습니다.",
        "제품 출시·서비스 적용·규제 집행의 실제 일정",
    ),
    "ai-deeptech": (
        "AI 모델·인프라·정책의 실제 성능과 적용 범위를 확인해야 하는 사안입니다.",
        "기술 경쟁력과 산업 파급력은 검증된 성능·비용·도입 사례를 통해 확인할 필요가 있습니다.",
        "모델 성능·가격·도입 사례와 공식 기술 문서",
    ),
    "semiconductors-mfg": (
        "반도체 수요·생산·투자·공급망의 실제 변화를 확인해야 하는 사안입니다.",
        "산업 영향은 수율·출하·고객사·투자 집행 등 후속 실적에서 확인할 필요가 있습니다.",
        "생산·출하·수율·투자 집행 관련 후속 지표",
    ),
    "bio-healthcare": (
        "임상·허가·사업화·보건정책의 공식 근거를 확인해야 하는 사안입니다.",
        "환자·의료기관·기업에 미치는 영향은 임상 결과와 허가·정책 결정에 따라 달라질 수 있습니다.",
        "규제기관·학회·기업의 공식 임상·허가 발표",
    ),
    "energy-mobility": (
        "에너지 가격·공급·설비와 모빌리티 정책·수요 변화를 함께 봐야 하는 사안입니다.",
        "실제 영향은 공급량·가격·판매·인프라 지표의 후속 변화로 확인할 필요가 있습니다.",
        "에너지 수급·가격 및 차량·인프라 후속 지표",
    ),
    "realestate-construction": (
        "주택 공급·가격·금융·건설 사업의 실제 변화를 확인해야 하는 사안입니다.",
        "가계와 건설업계 영향은 거래·분양·대출·PF 관련 후속 지표로 확인할 필요가 있습니다.",
        "거래·분양·대출·PF 관련 공식 통계와 후속 조치",
    ),
    "retail-consumer": (
        "가격·판매·유통채널·소비자 반응의 변화를 확인해야 하는 사안입니다.",
        "내수와 기업 실적 영향은 판매량·객단가·소비지표의 후속 변화로 확인할 필요가 있습니다.",
        "판매·가격·소비심리 관련 후속 지표",
    ),
    "society-environment": (
        "노동·인구·환경·안전 등 사회적 영향과 제도적 대응을 확인해야 하는 사안입니다.",
        "영향 범위는 공식 통계와 정책 집행, 현장 변화에 따라 달라질 수 있습니다.",
        "정부·지자체·관계기관의 공식 통계와 후속 대책",
    ),
    "culture-entertainment": (
        "콘텐츠 성과·시장 반응·권리 관계의 실제 변화를 확인해야 하는 사안입니다.",
        "산업 영향은 흥행·판매·시청·계약 등 검증 가능한 후속 성과로 확인할 필요가 있습니다.",
        "흥행·판매·시청·계약 관련 후속 성과",
    ),
    "science-future": (
        "연구 결과·실증·개발 일정의 검증 수준을 확인해야 하는 사안입니다.",
        "의미는 재현성·공식 데이터·후속 연구 및 실제 적용 가능성에 따라 달라질 수 있습니다.",
        "논문·기관 발표·실증 결과 등 공식 근거",
    ),
}

_PARTICLE_SUFFIXES = ("에서", "으로", "에게", "까지", "부터", "한테", "은", "는", "이", "가", "을", "를", "에", "로", "와", "과", "의", "도", "만")
_BAD_PATTERNS = ("을(를)", "이(가)", "은(는)", "에에 직접", "와와 직접", "과과 직접", "로로 전해졌", "경신로 전해졌")


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


def _looks_like_noise(fragment: str, title: str, source: str) -> bool:
    f = fragment.lower()
    if not fragment or fragment == title or fragment == source:
        return True
    if any(domain in f for domain in _NOISE_DOMAINS):
        return True
    if re.search(r"\b(?:https?://|www\.)", f) or re.search(r"\b[a-z0-9.-]+\.(?:com|co\.kr|kr|net|org)\b", f):
        return True
    return bool(re.fullmatch(r"(?:연합뉴스|뉴스|종합|속보|단독|머니투데이|한국경제|경향신문|전자신문)", fragment, re.I))


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
    return [m for m in _PUBLISHER_MARKERS if m.lower() in low and m.lower() not in selected]


def _strip_selected_title_and_source(piece: str, title: str, source: str) -> str:
    clean_title = _without_headline_tags(title)
    clean_piece = _without_headline_tags(_normalize(piece))
    if clean_title and clean_piece.startswith(clean_title):
        clean_piece = _normalize(clean_piece[len(clean_title):])
    for form in sorted({_normalize(source), _editorial_source(source)} - {""}, key=len, reverse=True):
        if clean_piece.startswith(form):
            clean_piece = _normalize(clean_piece[len(form):])
        if clean_piece.endswith(form):
            clean_piece = _normalize(clean_piece[:-len(form)])
    return clean_piece


def _summary_candidates(summary: str, title: str, source: str) -> List[str]:
    text = _normalize(summary)
    if not text:
        return []
    pieces = re.split(r"\s{2,}|\s+[|/]\s+|(?<=[.!?])\s+|\s+(?=\[[^\]]{1,30}\])", text)
    candidates: List[str] = []
    for raw_piece in pieces:
        piece = _normalize(re.sub(r"\[[^\]]{1,30}\]", " ", raw_piece))
        piece = _strip_selected_title_and_source(piece, title, source)
        if len(piece) < 12 or _looks_like_noise(piece, title, source):
            continue
        if any(domain in piece.lower() for domain in _NOISE_DOMAINS):
            continue
        if _publisher_hits(piece, source) or not _same_event_clause(piece, title):
            continue
        candidates.append(piece[:240].rstrip(" ,;"))
    return candidates


def _fallback_fact(source: str, title: str) -> str:
    clean_title = _without_headline_tags(title) or title
    return f"{source} 보도에 따르면, ‘{clean_title}’이라는 내용이 전해졌습니다. 세부 사실관계는 원문과 추가 근거에서 확인해야 합니다."


def _fact_text(raw: Dict[str, Any]) -> str:
    title = _normalize(raw.get("title", ""))
    raw_source = _normalize(raw.get("source", "")) or "주요 언론"
    source = _editorial_source(raw_source)
    candidates = _summary_candidates(raw.get("summary_raw", ""), title, raw_source)
    if candidates:
        clause = candidates[0]
        if clause.endswith(("다", "요", ".", "!", "?")):
            return f"{source} 보도에 따르면, {clause}"
    return _fallback_fact(source, title)


def _normalize_keyword(word: str) -> str:
    word = _normalize(word)
    for suffix in _PARTICLE_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            word = word[:-len(suffix)]
            break
    return word.strip("'\"‘’“”()[]{}.,:;!?…")


def _clean_keywords(title: str, summary: str, chapter_id: str) -> List[str]:
    title_keywords = extract_keywords(title, "", chapter_id)
    combined = extract_keywords(title, summary, chapter_id)
    merged: List[str] = []
    for word in [*title_keywords, *combined]:
        word = _normalize_keyword(word)
        if len(word) < 2 or word in {"산업전망", "시장동향", "정책분석"} or word in merged:
            continue
        merged.append(word)
    return merged[:4] or ["후속동향"]


def _event_focus(title: str, keywords: List[str]) -> str:
    return (_without_headline_tags(title) or "·".join(keywords[:2]) or "해당 사안")[:90]


def _semantic_gate(editorial: EditorialContent, keywords: List[str]) -> None:
    text = " ".join([editorial.fact, editorial.background, editorial.why_it_matters, *editorial.checkpoints])
    for bad in _BAD_PATTERNS:
        if bad in text:
            raise ValueError(f"editorial semantic gate rejected pattern: {bad}")
    if any(domain in text.lower() for domain in _NOISE_DOMAINS):
        raise ValueError("editorial semantic gate rejected relay domain exposure")
    for kw in keywords:
        if kw.endswith(("에서", "에게", "으로")):
            raise ValueError(f"editorial semantic gate rejected particle-tainted keyword: {kw}")


def build_editorial_for_article_v2(raw: Dict[str, Any]) -> EditorialContent:
    chapter_id = raw.get("chapter_id", "top-headlines")
    title = _normalize(raw.get("title", ""))
    raw_source = _normalize(raw.get("source", "")) or "주요 언론"
    source = _editorial_source(raw_source)
    summary = _normalize(raw.get("summary_raw", ""))
    context = _CHAPTER_CONTEXT.get(chapter_id, _CHAPTER_CONTEXT["top-headlines"])
    keywords = _clean_keywords(title, summary, chapter_id)
    focus = _event_focus(title, keywords)

    fact = _fact_text(raw)
    background = f"‘{focus}’ 관련 보도입니다. {context[0]} 현재 {source} 등 주요 매체의 후속 보도를 함께 확인할 필요가 있습니다."
    focus_terms = ", ".join(keywords[:3])
    why = f"핵심 확인 키워드는 {focus_terms}입니다. {context[1]}"

    fact_check = raw.get("fact_check") or {}
    evidence_domains: List[str] = []
    for url in fact_check.get("evidence_urls") or []:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        if not domain or any(noise == domain or domain.endswith("." + noise) for noise in _NOISE_DOMAINS):
            continue
        if domain not in evidence_domains:
            evidence_domains.append(domain)
    evidence_checkpoint = (
        f"독립 근거 도메인({', '.join(evidence_domains[:3])})의 후속 보도 일치 여부"
        if len(evidence_domains) >= 2 else "독립된 두 번째 근거 또는 공식 1차 자료의 추가 확인"
    )
    checkpoints = [f"‘{focus[:55]}’ 관련 공식 발표·원문 업데이트", evidence_checkpoint, context[2]]
    editorial = EditorialContent(fact=fact, background=background, why_it_matters=why, checkpoints=checkpoints)
    _semantic_gate(editorial, keywords)
    return editorial


def process_all_editorials(snapshot_articles: List[Dict[str, Any]]) -> List[Article]:
    print("=" * 70)
    print(" [Step 3] Evidence-aware Editorial Builder v3: Korean semantic quality gate")
    print("=" * 70)
    final_articles: List[Article] = []
    for idx, art in enumerate(snapshot_articles, 1):
        keywords = _clean_keywords(art["title"], art.get("summary_raw", ""), art["chapter_id"])
        editorial = build_editorial_for_article_v2(art)
        final_articles.append(Article(
            id=art["id"], chapter_id=art["chapter_id"], chapter_name=art["chapter_name"],
            title=art["title"], link=art["link"], source=art["source"],
            published_at=art.get("published_at", ""), summary_raw=art.get("summary_raw", ""),
            editorial=editorial, keywords=keywords, importance_score=art.get("importance_score", 5.0),
            fact_check=art.get("fact_check"), image=art.get("image"),
        ))
        if idx % 20 == 0 or idx == len(snapshot_articles):
            print(f"  └─ v3 에디토리얼 진행률: {idx}/{len(snapshot_articles)}")
    print(f" [Step 3 완료] {len(final_articles)}개 기사 Korean semantic gate PASS")
    print("=" * 70)
    return final_articles
