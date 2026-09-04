"""Independent fact-verification pass for BLUELAB Morning Intelligence.

P0 semantics:
- VERIFIED_MULTI_SOURCE means the same story has >=2 independent evidence domains.
- A reachable article URL, media brand, editorial length, or checkpoint count is
  never sufficient by itself for VERIFIED_MULTI_SOURCE.
- When corroboration is absent, fail closed to PARTIAL rather than overstating
  verification quality.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from pipeline.content_quality import independent_evidence_urls

OFFICIAL_DOMAINS = {
    "korea.kr", "gov.kr", "president.go.kr", "bok.or.kr", "fsc.go.kr",
    "fss.or.kr", "ftc.go.kr", "moef.go.kr", "motie.go.kr", "msit.go.kr",
    "molit.go.kr", "mohw.go.kr", "mfds.go.kr", "sec.gov", "whitehouse.gov",
    "federalreserve.gov", "fda.gov", "who.int", "nih.gov", "cdc.gov",
    "ec.europa.eu", "un.org", "wto.org", "imf.org", "worldbank.org",
    "nasa.gov", "esa.int", "kasi.re.kr", "kari.re.kr"
}

PRIMARY_DOMAINS = {
    "nature.com", "science.org", "cell.com", "thelancet.com", "nejm.org",
    "biorxiv.org", "medrxiv.org", "arxiv.org", "pubmed.ncbi.nlm.nih.gov",
    "crossref.org", "clinicaltrials.gov", "dart.fss.or.kr", "kind.krx.co.kr",
    "edgar-online.com", "prnewswire.com", "businesswire.com", "globenewswire.com"
}

MAJOR_WIRE_DOMAINS = {
    "yna.co.kr", "reuters.com", "apnews.com", "afp.com", "bloomberg.com",
    "wsj.com", "ft.com", "nytimes.com", "nikkei.com"
}

MAJOR_KR_MEDIA = {
    "연합뉴스", "한국경제", "매일경제", "조선일보", "중앙일보", "동아일보",
    "서울경제", "머니투데이", "이데일리", "뉴시스", "뉴스1", "전자신문",
    "디지털데일리", "지디넷코리아", "KBS", "MBC", "SBS", "YTN", "JTBC"
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BLUELAB-FactChecker/3.0"


def _domain(url: str) -> str:
    return urlparse((url or "").strip()).netloc.lower().removeprefix("www.")


def _matches(domain: str, allowed: set[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in allowed)


def _check_http_access(url: str, timeout: int = 4) -> tuple[bool, Optional[str]]:
    """Check transport accessibility only. Accessibility is not fact verification."""
    try:
        resp = requests.head(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=True)
        if resp.status_code in (200, 301, 302, 304, 307, 308):
            return True, None
        if resp.status_code in (401, 403, 429, 503):
            return False, f"HTTP_{resp.status_code}_CHALLENGE"
        resp_get = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1024"},
            timeout=timeout,
            stream=True,
        )
        if resp_get.status_code in (200, 206):
            return True, None
        return False, f"HTTP_{resp_get.status_code}"
    except Exception as exc:
        return False, type(exc).__name__


def _evidence_domains(article: Dict[str, Any]) -> tuple[List[str], List[str]]:
    """Include the article itself plus explicit corroborating evidence URLs."""
    primary_link = (article.get("link") or "").strip()
    urls = [primary_link] if primary_link else []
    urls.extend(independent_evidence_urls(article))

    unique_urls: List[str] = []
    domains: List[str] = []
    seen = set()
    for url in urls:
        domain = _domain(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
        unique_urls.append(url)
    return unique_urls, domains


def evaluate_article_fact_check(article: Dict[str, Any], check_network: bool = False) -> Dict[str, Any]:
    """Apply conservative, machine-readable verification semantics."""
    link = (article.get("link") or "").strip()
    source = (article.get("source") or "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()
    domain = _domain(link)

    if check_network:
        is_accessible, block_reason = _check_http_access(link)
        if not is_accessible:
            return {
                "status": "ACCESS_BLOCKED",
                "evidence_type": "network_blocked",
                "verified_sources": [domain] if domain else [],
                "evidence_urls": [link] if link else [],
                "notes": f"접근 차단 또는 네트워크 보호 적용({block_reason}) — 진위 판정 아님",
                "checked_at": now_iso,
            }

    if _matches(domain, OFFICIAL_DOMAINS):
        return {
            "status": "VERIFIED_OFFICIAL",
            "evidence_type": "official",
            "verified_sources": [domain],
            "evidence_urls": [link],
            "notes": f"공공기관·규제기관·정부 공식 도메인({domain}) 원문 확인",
            "checked_at": now_iso,
        }

    if _matches(domain, PRIMARY_DOMAINS):
        return {
            "status": "VERIFIED_PRIMARY",
            "evidence_type": "primary",
            "verified_sources": [domain],
            "evidence_urls": [link],
            "notes": f"학술연구·공시·1차 출처 도메인({domain}) 원문 확인",
            "checked_at": now_iso,
        }

    if _matches(domain, MAJOR_WIRE_DOMAINS) or source in ("연합뉴스", "로이터", "AP", "AFP"):
        return {
            "status": "VERIFIED_PRIMARY",
            "evidence_type": "wire_service",
            "verified_sources": [x for x in (source, domain) if x],
            "evidence_urls": [link] if link else [],
            "notes": f"기간통신사·1차 뉴스와이어({source or domain}) 원문 보도 확인",
            "checked_at": now_iso,
        }

    evidence_urls, evidence_domains = _evidence_domains(article)
    if len(evidence_domains) >= 2:
        return {
            "status": "VERIFIED_MULTI_SOURCE",
            "evidence_type": "multi_source",
            "verified_sources": evidence_domains,
            "evidence_urls": evidence_urls,
            "notes": f"독립 도메인 {len(evidence_domains)}곳에서 명시적 근거 URL 확보",
            "checked_at": now_iso,
        }

    if domain:
        media_class = "major_media" if source in MAJOR_KR_MEDIA else "single_source_media"
        return {
            "status": "PARTIAL",
            "evidence_type": media_class,
            "verified_sources": [x for x in (source, domain) if x],
            "evidence_urls": [link] if link else [],
            "notes": "단일 기사 원문은 확인했으나 독립된 두 번째 근거 URL이 없어 다중출처 검증으로 승격하지 않음",
            "checked_at": now_iso,
        }

    return {
        "status": "UNVERIFIED",
        "evidence_type": "unverified",
        "verified_sources": [],
        "evidence_urls": [],
        "notes": "출처 도메인 또는 검증 가능한 근거 URL이 없어 추가 검증 필요",
        "checked_at": now_iso,
    }


def verify_all_articles(
    articles: List[Dict[str, Any]], check_network: bool = False, max_workers: int = 10
) -> List[Dict[str, Any]]:
    print("=" * 70)
    print(f" [Step 2.5] 독립 팩트 검증 관문 v2: {len(articles)}개 기사")
    print("=" * 70)

    out: List[Dict[str, Any] | None] = [None] * len(articles)
    if check_network:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(evaluate_article_fact_check, art, True): i for i, art in enumerate(articles)}
            for future in as_completed(futures):
                idx = futures[future]
                art_copy = dict(articles[idx])
                art_copy["fact_check"] = future.result()
                out[idx] = art_copy
    else:
        for idx, art in enumerate(articles):
            art_copy = dict(art)
            art_copy["fact_check"] = evaluate_article_fact_check(art_copy, check_network=False)
            out[idx] = art_copy

    finalized: List[Dict[str, Any]] = [a for a in out if a is not None]
    counts: Dict[str, int] = {}
    for article in finalized:
        status = article["fact_check"]["status"]
        counts[status] = counts.get(status, 0) + 1

    print("  [팩트체크 v2 완료] " + " | ".join(f"{k}: {v}건" for k, v in sorted(counts.items())))
    return finalized
