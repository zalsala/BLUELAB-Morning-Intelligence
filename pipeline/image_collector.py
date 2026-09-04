"""Exact-article representative image collector with conservative provenance.

Policy:
- discover only images declared by the selected exact article page
- verify the image response is an actual image
- compute a bounded content hash for duplicate suppression
- never fabricate, search externally, or substitute unrelated stock images
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; BLUELAB-Morning-Intelligence/1.0; image-provenance)"
ARTICLE_TIMEOUT = 5
IMAGE_TIMEOUT = 5
MAX_HTML_BYTES = 1_200_000
MAX_IMAGE_HASH_BYTES = 96_000
MAX_WORKERS = 12

_BAD_URL_WORDS = (
    "logo", "icon", "avatar", "profile", "favicon", "sprite", "placeholder",
    "default-image", "default_image", "noimage", "no-image", "banner-ad", "advert",
)


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


def _jsonld_image(soup: BeautifulSoup) -> Optional[str]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for obj in _iter_jsonld(data):
            value = obj.get("image")
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("url"), str):
                return value["url"]
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        return item
                    if isinstance(item, dict) and isinstance(item.get("url"), str):
                        return item["url"]
    return None


def _meta_content(soup: BeautifulSoup, *selectors: Tuple[str, str]) -> Optional[str]:
    for attr, value in selectors:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            return str(tag.get("content")).strip()
    return None


def extract_declared_image(html: str, page_url: str) -> Tuple[Optional[str], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = [
        ("og:image", _meta_content(soup, ("property", "og:image"), ("name", "og:image"))),
        ("twitter:image", _meta_content(soup, ("name", "twitter:image"), ("property", "twitter:image"))),
        ("jsonld:image", _jsonld_image(soup)),
    ]
    for method, raw in candidates:
        if not raw:
            continue
        url = urljoin(page_url, raw.strip())
        parsed = urlparse(url)
        low = url.lower()
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if any(word in low for word in _BAD_URL_WORDS):
            continue
        if low.endswith((".svg", ".ico")):
            continue
        return url, method
    return None, None


def _bounded_html(resp: requests.Response) -> str:
    parts: List[bytes] = []
    total = 0
    for chunk in resp.iter_content(32768):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_HTML_BYTES:
            break
        parts.append(chunk)
    return b"".join(parts).decode(resp.encoding or "utf-8", errors="replace")


def _verify_image(url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "UNVERIFIED", "content_type": None, "content_hash": None}
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8", "Range": f"bytes=0-{MAX_IMAGE_HASH_BYTES-1}"},
            timeout=IMAGE_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        if resp.status_code not in (200, 206):
            result["status"] = f"HTTP_{resp.status_code}"
            return result
        ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].lower().strip()
        if not ctype.startswith("image/") or ctype in ("image/svg+xml", "image/x-icon"):
            result["status"] = "NON_RASTER_IMAGE"
            return result
        data = bytearray()
        for chunk in resp.iter_content(16384):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) >= MAX_IMAGE_HASH_BYTES:
                break
        if len(data) < 1024:
            result["status"] = "TOO_SMALL"
            return result
        result.update({
            "status": "VERIFIED",
            "content_type": ctype,
            "content_hash": hashlib.sha256(bytes(data[:MAX_IMAGE_HASH_BYTES])).hexdigest(),
        })
        return result
    except requests.Timeout:
        result["status"] = "TIMEOUT"
    except requests.RequestException as exc:
        result["status"] = type(exc).__name__
    return result


def _collect_one(article: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(article)
    link = (out.get("link") or "").strip()
    candidate: Dict[str, Any] = {
        "status": "NO_CANDIDATE", "url": None, "method": None,
        "page_url": link, "page_domain": urlparse(link).netloc.lower().removeprefix("www."),
        "content_type": None, "content_hash": None,
    }
    if not link.startswith(("http://", "https://")):
        out["image_candidate"] = candidate
        return out
    try:
        resp = requests.get(
            link,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=ARTICLE_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        if resp.status_code != 200:
            candidate["status"] = f"PAGE_HTTP_{resp.status_code}"
            out["image_candidate"] = candidate
            return out
        if "html" not in (resp.headers.get("content-type") or "").lower():
            candidate["status"] = "PAGE_NON_HTML"
            out["image_candidate"] = candidate
            return out
        html = _bounded_html(resp)
        image_url, method = extract_declared_image(html, link)
        if not image_url:
            out["image_candidate"] = candidate
            return out
        verified = _verify_image(image_url)
        candidate.update({"url": image_url, "method": method, **verified})
    except requests.Timeout:
        candidate["status"] = "PAGE_TIMEOUT"
    except requests.RequestException as exc:
        candidate["status"] = f"PAGE_{type(exc).__name__}"
    except Exception as exc:
        candidate["status"] = f"PAGE_PARSE_{type(exc).__name__}"
    out["image_candidate"] = candidate
    return out


def collect_article_images(articles: List[Dict[str, Any]], max_workers: int = MAX_WORKERS) -> List[Dict[str, Any]]:
    """Collect and verify article-declared representative images, preserving order."""
    print("=" * 70)
    print(f" [Step 2.8] Exact-article image discovery: {len(articles)}개")
    print("=" * 70)
    results: List[Optional[Dict[str, Any]]] = [None] * len(articles)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_collect_one, art): idx for idx, art in enumerate(articles)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                fallback = dict(articles[idx])
                fallback["image_candidate"] = {"status": "COLLECTOR_ERROR", "url": None, "method": None, "page_url": fallback.get("link"), "page_domain": None, "content_type": None, "content_hash": None}
                results[idx] = fallback
    final = [x for x in results if x is not None]

    # Duplicate suppression is based on fetched image content, not URL alone.
    seen_hashes = set()
    counts: Dict[str, int] = {}
    for art in final:
        cand = dict(art.get("image_candidate") or {})
        if cand.get("status") == "VERIFIED" and cand.get("content_hash"):
            digest = cand["content_hash"]
            if digest in seen_hashes:
                cand["status"] = "DUPLICATE_IMAGE"
                cand["url"] = None
            else:
                seen_hashes.add(digest)
        art["image_candidate"] = cand
        status = cand.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    print("  [Image discovery] " + " | ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("=" * 70)
    return final
