"""Bounded exact-URL article-body validation for editorial grounding.

The collector never invents content and never makes body access a publication
requirement: inaccessible/paywalled pages retain the safe headline fallback.
Only compact validation metadata is persisted; full article text is not stored.
A short validated evidence span may be carried transiently under a private key
for downstream editorial generation and is intentionally omitted from Article.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from pipeline.content_quality import informative_title_tokens

USER_AGENT = "Mozilla/5.0 (compatible; BLUELAB-Morning-Intelligence/1.0; article-validation)"
MAX_DOWNLOAD_BYTES = 1_500_000
MIN_BODY_CHARS = 220
TIMEOUT_SECONDS = 5
MAX_WORKERS = 12
MAX_EVIDENCE_SPAN_CHARS = 240


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _iter_jsonld(node: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        graph = node.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_jsonld(item)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_jsonld(item)


def _extract_jsonld_body(soup: BeautifulSoup) -> Optional[str]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for obj in _iter_jsonld(data):
            body = obj.get("articleBody")
            if isinstance(body, str) and len(_norm(body)) >= MIN_BODY_CHARS:
                return _norm(body)
    return None


def _extract_article_body(soup: BeautifulSoup) -> Optional[str]:
    article = soup.find("article")
    nodes = article.find_all("p") if article else soup.find_all("p")
    parts: List[str] = []
    seen = set()
    for node in nodes:
        text = _norm(node.get_text(" ", strip=True))
        if len(text) < 30 or text in seen:
            continue
        low = text.lower()
        if any(noise in low for noise in ("무단전재", "재배포 금지", "copyright", "기자 =", "구독", "로그인")):
            continue
        seen.add(text)
        parts.append(text)
        if sum(len(x) for x in parts) >= 6000:
            break
    body = _norm(" ".join(parts))
    return body if len(body) >= MIN_BODY_CHARS else None


def _event_overlap(title: str, body: str) -> Tuple[bool, float, List[str]]:
    title_tokens = informative_title_tokens(title)
    if not title_tokens:
        return False, 0.0, []
    body_tokens = informative_title_tokens(body[:6000])
    shared = sorted(title_tokens & body_tokens)
    ratio = len(shared) / max(1, len(title_tokens))
    return len(shared) >= 2 and ratio >= 0.40, round(ratio, 3), shared[:8]


def _extract_evidence_span(title: str, body: str) -> Optional[str]:
    """Return one short, title-grounded sentence for transient editorial use."""
    title_tokens = informative_title_tokens(title)
    if not title_tokens:
        return None
    candidates = re.split(r"(?<=[.!?다요])\s+", _norm(body))
    ranked: List[Tuple[float, int, str]] = []
    for sentence in candidates:
        sentence = _norm(sentence)
        if len(sentence) < 30 or len(sentence) > MAX_EVIDENCE_SPAN_CHARS:
            continue
        tokens = informative_title_tokens(sentence)
        shared = title_tokens & tokens
        if len(shared) < 2:
            continue
        coverage = len(shared) / max(1, len(title_tokens))
        if coverage < 0.40:
            continue
        ranked.append((coverage, len(shared), sentence))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], -item[1], len(item[2])))
    return ranked[0][2]


def _fetch_one(article: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(article)
    fact = dict(out.get("fact_check") or {})
    link = (out.get("link") or "").strip()
    status: Dict[str, Any] = {
        "status": "UNAVAILABLE",
        "method": None,
        "body_chars": 0,
        "title_overlap": 0.0,
        "shared_title_tokens": [],
    }
    if not link.startswith(("http://", "https://")):
        fact["body_validation"] = status
        out["fact_check"] = fact
        return out
    try:
        resp = requests.get(
            link,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=TIMEOUT_SECONDS,
            allow_redirects=True,
            stream=True,
        )
        if resp.status_code != 200:
            status["status"] = f"HTTP_{resp.status_code}"
            fact["body_validation"] = status
            out["fact_check"] = fact
            return out
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            status["status"] = "NON_HTML"
            fact["body_validation"] = status
            out["fact_check"] = fact
            return out
        chunks: List[bytes] = []
        total = 0
        for chunk in resp.iter_content(32768):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                break
            chunks.append(chunk)
        html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        body = _extract_jsonld_body(soup)
        method = "jsonld_articleBody" if body else None
        if not body:
            body = _extract_article_body(soup)
            method = "article_paragraphs" if body else None
        if not body:
            status["status"] = "NO_QUALIFIED_BODY"
        else:
            passed, ratio, shared = _event_overlap(out.get("title", ""), body)
            status.update({
                "status": "VALIDATED" if passed else "EVENT_MISMATCH",
                "method": method,
                "body_chars": len(body),
                "title_overlap": ratio,
                "shared_title_tokens": shared,
            })
            if passed:
                evidence_span = _extract_evidence_span(out.get("title", ""), body)
                if evidence_span:
                    out["_body_evidence_span"] = evidence_span
    except requests.Timeout:
        status["status"] = "TIMEOUT"
    except requests.RequestException as exc:
        status["status"] = type(exc).__name__
    except Exception as exc:
        status["status"] = f"PARSE_{type(exc).__name__}"

    fact["body_validation"] = status
    out["fact_check"] = fact
    return out


def validate_article_bodies(articles: List[Dict[str, Any]], max_workers: int = MAX_WORKERS) -> List[Dict[str, Any]]:
    """Validate exact article bodies concurrently while preserving input order."""
    print("=" * 70)
    print(f" [Step 2.7] Exact-URL article body validation: {len(articles)}개")
    print("=" * 70)
    results: List[Optional[Dict[str, Any]]] = [None] * len(articles)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, art): idx for idx, art in enumerate(articles)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                fallback = dict(articles[idx])
                fact = dict(fallback.get("fact_check") or {})
                fact["body_validation"] = {"status": "COLLECTOR_ERROR", "method": None, "body_chars": 0, "title_overlap": 0.0, "shared_title_tokens": []}
                fallback["fact_check"] = fact
                results[idx] = fallback
    final = [x for x in results if x is not None]
    counts: Dict[str, int] = {}
    grounded = 0
    for art in final:
        status = ((art.get("fact_check") or {}).get("body_validation") or {}).get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
        if art.get("_body_evidence_span"):
            grounded += 1
    print("  [Body validation] " + " | ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"  [Grounding candidates] transient evidence_span={grounded}/{len(final)}")
    print("=" * 70)
    return final
