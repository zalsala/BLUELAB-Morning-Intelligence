"""
pipeline/image_provenance.py
BLUELAB Morning Intelligence 기사 이미지 출처 검증 모듈

IMAGE POLICY:
Every rendered story must either contain verified image provenance or explicit null.
Never substitute an unrelated image merely to fill a visual slot.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# 신뢰 가능한 이미지 CDN 및 언론사 이미지 호스트 허용 목록
REPUTABLE_IMAGE_HOSTS = {
    "pstatic.net", "daumcdn.net", "ytimg.com", "googleusercontent.com",
    "cloudfront.net", "akamaihd.net", "fastly.net", "img-s-msn-com.akamaized.net",
    "yna.co.kr", "hankyung.com", "mk.co.kr", "chosun.com", "donga.com",
    "joongang.co.kr", "hani.co.kr", "khan.co.kr", "sedaily.com", "mt.co.kr",
    "edaily.co.kr", "newsis.com", "news1.kr", "etnews.com", "kbs.co.kr",
    "imbc.com", "sbs.co.kr", "ytn.co.kr", "jtbc.co.kr", "reuters.com",
    "apnews.com", "bloomberg.com"
}


def audit_image_provenance(article: Dict[str, Any]) -> Dict[str, Any]:
    """개별 기사의 이미지 출처를 엄격하게 감사하고, 검증되지 않은 이미지는 explicit null 처리"""
    raw_img = article.get("image") or article.get("image_url")
    link = (article.get("link") or "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    if not raw_img:
        return {
            "url": None,
            "source_domain": None,
            "status": "EXPLICIT_NULL",
            "verified_at": now_iso
        }

    # 문자열 URL이거나 딕셔너리 형태 처리
    img_url = raw_img if isinstance(raw_img, str) else raw_img.get("url")
    if not img_url or not isinstance(img_url, str):
        return {
            "url": None,
            "source_domain": None,
            "status": "EXPLICIT_NULL",
            "verified_at": now_iso
        }

    img_url = img_url.strip()
    parsed_img = urlparse(img_url)
    if parsed_img.scheme not in ("http", "https") or not parsed_img.netloc:
        return {
            "url": None,
            "source_domain": None,
            "status": "EXPLICIT_NULL",
            "verified_at": now_iso
        }

    img_domain = parsed_img.netloc.lower()
    if img_domain.startswith("www."):
        img_domain = img_domain[4:]

    article_domain = urlparse(link).netloc.lower()
    if article_domain.startswith("www."):
        article_domain = article_domain[4:]

    # 도메인이 기사 원문 도메인과 일치하거나, 공인 미디어 CDN 호스트에 속하는지 검증
    is_same_domain = (img_domain == article_domain or img_domain.endswith("." + article_domain))
    is_reputable_host = any(img_domain == h or img_domain.endswith("." + h) for h in REPUTABLE_IMAGE_HOSTS)

    if is_same_domain or is_reputable_host:
        return {
            "url": img_url,
            "source_domain": img_domain,
            "status": "VERIFIED_PROVENANCE",
            "verified_at": now_iso
        }

    # 출처 불분명 이미지는 절대 대체하지 않고 명시적 null
    return {
        "url": None,
        "source_domain": None,
        "status": "EXPLICIT_NULL",
        "verified_at": now_iso
    }


def audit_all_images(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """전체 기사에 대해 이미지 출처 정책(VERIFIED_PROVENANCE 또는 EXPLICIT_NULL)을 일괄 적용"""
    print("=" * 70)
    print(f" [Step 2.6] 이미지 출처 검증 관문 (Image Provenance Gate) 가동: {len(articles)}개 기사")
    print("=" * 70)

    out = []
    verified_count = 0
    null_count = 0

    for art in articles:
        art_copy = dict(art)
        prov = audit_image_provenance(art_copy)
        art_copy["image"] = prov
        if prov["status"] == "VERIFIED_PROVENANCE":
            verified_count += 1
        else:
            null_count += 1
        out.append(art_copy)

    print(f"  [이미지 출처 검증 완료] VERIFIED_PROVENANCE={verified_count}건 | EXPLICIT_NULL={null_count}건")
    return out
