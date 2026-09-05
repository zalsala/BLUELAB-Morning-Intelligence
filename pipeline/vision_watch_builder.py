"""Build the independent VISION RESEARCH WATCH production chapter."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from scripts.collect_vision_research import PROVIDERS, QUERY_FILE, dedupe
from scripts.select_vision_research import select

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "vision-research-policy.json"
CHAPTER_ID = "vision-research-watch"
CHAPTER_NAME = "안경 · 콘택트렌즈 · 안과 · 검안 · 시과학 · 근시관리"
UA = "BLUELAB-Morning-Intelligence/1.0"

CLINICAL_MEANING = {
    "myopia": "근시 진행과 근시관리 전략의 근거를 보완하는 연구입니다. 연령, 개입 방식, 축장·굴절 변화량과 추적기간을 원문에서 함께 확인해야 임상 적용 범위를 판단할 수 있습니다.",
    "binocular": "양안시·사시·조절·폭주 평가와 처치 판단에 참고할 수 있는 연구입니다. 대상군의 진단 기준과 검사 조건, 증상·기능 결과를 실제 진료 맥락과 대조해야 합니다.",
    "contact_cornea": "콘택트렌즈·각막·안구표면 관리에 참고할 수 있는 근거입니다. 렌즈 재질, 착용시간, 각막/눈물막 평가법과 이상반응을 원문에서 확인해야 합니다.",
    "ophthalmology": "안과 질환의 진단·치료·예후 판단과 관련된 근거입니다. 질환 단계, 치료군, 주요 결과지표와 안전성 결과를 원문 기준으로 해석해야 합니다.",
    "vision_science": "시각기능과 시과학 기전을 이해하는 데 참고할 수 있는 연구입니다. 실험 조건과 측정지표가 실제 임상 시기능 검사와 어떻게 연결되는지 구분해 해석해야 합니다.",
    "optometry": "굴절·시력검사·검안 및 시기능 관리에 참고할 수 있는 연구입니다. 검사 프로토콜, 대상군 특성, 임상적으로 의미 있는 변화량을 원문에서 확인해야 합니다.",
}


def _domain(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")


def _resolve_exact_url(url: str) -> str:
    """Resolve DOI identifiers to the publisher article URL when possible."""
    if _domain(url) not in {"doi.org", "dx.doi.org"}:
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            final = resp.geturl()
        if final.startswith(("http://", "https://")) and _domain(final) not in {"doi.org", "dx.doi.org"}:
            return final
    except Exception:
        pass
    return url


def _collect(days: int, limit_per_source: int = 3) -> tuple[list[dict], list[dict]]:
    cfg = json.loads(QUERY_FILE.read_text(encoding="utf-8"))
    records: list[dict] = []
    errors: list[dict] = []
    for family in cfg["families"]:
        for provider, fn in PROVIDERS.items():
            try:
                records.extend(fn(family, days, limit_per_source))
            except Exception as exc:
                errors.append({"provider": provider, "topic_id": family["id"], "error": f"{type(exc).__name__}: {exc}"})
    return dedupe(records), errors


def _publication_iso(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 10 and text[4] == "-":
        return text + "T00:00:00+00:00"
    return text


def _source_name(item: dict) -> str:
    journal = (item.get("journal") or "").strip()
    if journal:
        return journal
    return {
        "pubmed": "PubMed",
        "europe-pmc": "Europe PMC",
        "crossref": "Crossref / DOI",
        "clinicaltrials": "ClinicalTrials.gov",
    }.get(item.get("collector_source"), item.get("collector_source") or "Scholarly source")


def _article(item: dict, checked_at: str) -> dict:
    topic = item.get("topic_id") or "vision_science"
    evidence = item.get("evidence_type") or "RESEARCH / ISSUE"
    design = (item.get("study_type") or evidence).strip()
    title = (item.get("title") or "").strip()
    url = (item.get("exact_source_url") or item.get("url") or "").strip()
    abstract = (item.get("abstract") or "").strip()
    clinical = CLINICAL_MEANING.get(topic, CLINICAL_MEANING["vision_science"])
    limitation = (
        "자동 수집된 서지·등록 메타데이터만으로 표본 구성, 효과크기, 탈락률, 통계분석, 연구비와 이해상충을 모두 확정할 수 없습니다. "
        "Methods·Results·Funding/COI 원문을 확인한 뒤 임상적 결론을 내려야 합니다."
    )
    identity = item.get("doi") or item.get("pmid") or item.get("nct_id") or url or title
    art_id = hashlib.sha256(f"vision|{identity}".encode("utf-8")).hexdigest()[:16]
    source_domain = _domain(url)
    fact = f"근거유형은 {evidence}, 연구설계 표기는 {design}입니다. 원문 제목은 ‘{title}’이며 정확한 논문·등록 링크를 기준으로 검토합니다."
    return {
        "id": art_id,
        "chapter_id": CHAPTER_ID,
        "chapter_name": CHAPTER_NAME,
        "title": title,
        "link": url,
        "source": _source_name(item),
        "published_at": _publication_iso(item.get("publication_date", "")),
        "summary_raw": abstract or title,
        "editorial": {
            "fact": fact,
            "background": f"임상적 의미: {clinical}",
            "why_it_matters": f"한계·이해상충 확인: {limitation}",
            "checkpoints": [
                "표본 수·대상 연령·진단 기준과 주요 효과크기를 원문에서 확인",
                "추적기간·탈락률·통계분석 및 이상반응/안전성 결과 확인",
                "Funding·Conflict of Interest와 기존 가이드라인/체계적 문헌고찰과의 일치 여부 확인",
            ],
        },
        "keywords": [topic, evidence, "VISION RESEARCH WATCH"],
        "importance_score": float(item.get("selection_score") or 5),
        "fact_check": {
            "status": "VERIFIED_PRIMARY",
            "evidence_type": "primary",
            "verified_sources": [source_domain] if source_domain else [],
            "notes": "학술 데이터베이스 또는 임상시험 등록의 정확한 원문/서지 링크를 사용했습니다. 연구 결과 해석은 원문 전문 확인이 필요합니다.",
            "checked_at": checked_at,
            "body_validation": {"status": "NO_QUALIFIED_BODY"},
        },
        "image": {"url": None, "source_domain": None, "status": "EXPLICIT_NULL", "verified_at": None},
        "research_watch": {
            "topic_id": topic,
            "topic_label": item.get("topic_label", ""),
            "evidence_type": evidence,
            "study_design": design,
            "clinical_meaning_ko": clinical,
            "limitations_conflicts_ko": limitation,
            "journal": item.get("journal", ""),
            "authors": item.get("authors", []),
            "doi": item.get("doi", ""),
            "pmid": item.get("pmid", ""),
            "nct_id": item.get("nct_id", ""),
            "exact_source_url": url,
        },
    }


def build_vision_watch(target: int = 10) -> tuple[dict, dict]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    today = dt.date.today()
    windows = [7, 14, int(policy.get("max_search_window_days", 30))]
    max_share = float(policy.get("max_single_topic_share", 0.4))
    allowed_kinds = set(policy.get("allowed_kinds") or [])
    last = None
    provider_errors: list[dict] = []

    for days in windows:
        candidates, errors = _collect(int(days), limit_per_source=3)
        provider_errors.extend(errors)
        if allowed_kinds:
            candidates = [x for x in candidates if (x.get("evidence_type") or "RESEARCH / ISSUE") in allowed_kinds]
        chosen, topic_counts, source_counts, reject_counts, eligible = select(candidates, target, max_share, today)
        last = (days, candidates, chosen, topic_counts, source_counts, reject_counts, eligible)
        if len(chosen) >= target:
            break

    if last is None:
        raise RuntimeError("vision research acquisition produced no evaluation window")
    days, candidates, chosen, topic_counts, source_counts, reject_counts, eligible = last
    if len(chosen) != target:
        raise RuntimeError(f"VISION RESEARCH WATCH requires exactly {target}; selected={len(chosen)} eligible={eligible} window={days}d")

    # Resolve DOI identifiers only for the final ten selected records. This
    # preserves DOI provenance while measuring source diversity at the actual
    # publisher/registry endpoint whenever the resolver is reachable.
    for item in chosen:
        item["exact_source_url"] = _resolve_exact_url(item.get("url", ""))

    exact_domains = {_domain(x.get("exact_source_url", "")) for x in chosen if _domain(x.get("exact_source_url", ""))}
    min_domains = int(policy.get("minimum_unique_source_domains", 5))
    if len(exact_domains) < min_domains:
        raise RuntimeError(f"VISION RESEARCH WATCH source diversity failed: domains={len(exact_domains)} < {min_domains}; domains={sorted(exact_domains)}")

    checked_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    articles = [_article(x, checked_at) for x in chosen]
    chapter = {
        "id": CHAPTER_ID,
        "name": CHAPTER_NAME,
        "name_en": "Vision / Optometry / Ophthalmology Research Watch",
        "icon": "👁️",
        "description": "근시·양안시·사시·조절/폭주·콘택트렌즈·각막·안과·검안·시과학의 독립 학술 근거 모니터링",
        "count": len(articles),
        "articles": articles,
    }
    report = {
        "schema_version": "vision-research-watch-v1",
        "generated_at": checked_at,
        "window_days": days,
        "candidate_count": len(candidates),
        "eligible_count": eligible,
        "selected_count": len(chosen),
        "coverage_status": "PASS",
        "topic_counts": dict(topic_counts),
        "collector_source_counts": dict(source_counts),
        "exact_source_domains": sorted(exact_domains),
        "reject_counts": dict(reject_counts),
        "provider_errors": provider_errors,
        "selected": [a["research_watch"] | {"title": a["title"], "source": a["source"], "published_at": a["published_at"]} for a in articles],
    }
    return chapter, report
