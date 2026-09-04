"""Strict image provenance gate for BLUELAB Morning Intelligence.

An image is publishable only when it was declared by the selected exact article
page and the image collector independently verified an actual raster response.
Unverified, duplicate, placeholder, or missing images remain explicit null.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse


def _null(now_iso: str, reason: str = "UNVERIFIED") -> Dict[str, Any]:
    return {
        "url": None,
        "source_domain": None,
        "status": "EXPLICIT_NULL",
        "verified_at": now_iso,
        "reason": reason,
    }


def audit_image_provenance(article: Dict[str, Any]) -> Dict[str, Any]:
    """Approve only exact-page-declared, HTTP-verified raster image candidates."""
    now_iso = datetime.now(timezone.utc).isoformat()
    link = (article.get("link") or "").strip()
    candidate = article.get("image_candidate") or {}
    if not isinstance(candidate, dict):
        return _null(now_iso, "NO_CANDIDATE")

    if candidate.get("status") != "VERIFIED":
        return _null(now_iso, str(candidate.get("status") or "NO_CANDIDATE"))

    img_url = (candidate.get("url") or "").strip()
    page_url = (candidate.get("page_url") or "").strip()
    method = candidate.get("method")
    content_type = (candidate.get("content_type") or "").lower()
    content_hash = candidate.get("content_hash")

    # Provenance chain must point back to the selected exact article URL.
    if not link or page_url != link:
        return _null(now_iso, "PAGE_URL_MISMATCH")
    if method not in {"og:image", "twitter:image", "jsonld:image"}:
        return _null(now_iso, "UNSUPPORTED_DECLARATION")
    if not content_type.startswith("image/") or content_type in {"image/svg+xml", "image/x-icon"}:
        return _null(now_iso, "INVALID_IMAGE_CONTENT_TYPE")
    if not content_hash or len(str(content_hash)) != 64:
        return _null(now_iso, "MISSING_CONTENT_HASH")

    parsed = urlparse(img_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return _null(now_iso, "INVALID_IMAGE_URL")

    img_domain = parsed.netloc.lower().removeprefix("www.")
    article_domain = urlparse(link).netloc.lower().removeprefix("www.")
    return {
        "url": img_url,
        "source_domain": img_domain,
        "article_domain": article_domain,
        "status": "VERIFIED_PROVENANCE",
        "declaration_method": method,
        "content_type": content_type,
        "content_hash": content_hash,
        "verified_at": now_iso,
    }


def audit_all_images(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply provenance policy to every article without filling unavailable slots."""
    print("=" * 70)
    print(f" [Step 2.9] 이미지 출처 검증 관문 (Image Provenance Gate): {len(articles)}개")
    print("=" * 70)
    out: List[Dict[str, Any]] = []
    verified = 0
    nulls = 0
    reasons: Dict[str, int] = {}
    for art in articles:
        copied = dict(art)
        prov = audit_image_provenance(copied)
        copied["image"] = prov
        # Candidate is internal acquisition metadata; final bundle needs only provenance.
        copied.pop("image_candidate", None)
        if prov["status"] == "VERIFIED_PROVENANCE":
            verified += 1
        else:
            nulls += 1
            reason = prov.get("reason", "UNKNOWN")
            reasons[reason] = reasons.get(reason, 0) + 1
        out.append(copied)
    reason_text = " | ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
    print(f"  [이미지 출처 검증 완료] VERIFIED_PROVENANCE={verified} | EXPLICIT_NULL={nulls}" + (f" | {reason_text}" if reason_text else ""))
    print("=" * 70)
    return out
