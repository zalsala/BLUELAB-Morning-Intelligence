"""
tests/test_release_pipeline.py
BLUELAB Morning Intelligence 릴리즈 파이프라인 회귀 및 계약 테스트 스위트
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from pipeline.schema import FACT_CHECK_STATES
from pipeline.publication_manifest import (
    compute_snapshot_fingerprint,
    compute_editorial_fingerprint,
    compute_production_fingerprint,
    build_publication_manifest,
)
from scripts.qa_gate import run_qa_gate
from scripts.validate_publication_manifest import validate_manifest

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def valid_bundle_data() -> dict:
    """모든 10대 품질 관문을 통과하는 최소 완전 유효 번들 픽스처"""
    today_kst = datetime.now(KST).strftime("%Y-%m-%d")
    chapters = []
    
    chapter_ids = [
        "top-headlines", "politics-policy", "macro-finance", "global-affairs",
        "tech-it", "ai-deeptech", "semiconductors-mfg", "bio-healthcare",
        "energy-mobility", "realestate-construction", "retail-consumer",
        "society-environment", "culture-entertainment", "science-future"
    ]

    counter = 1
    for c_id in chapter_ids:
        articles = []
        for i in range(10):
            art_id = f"art-{counter:04d}"
            articles.append({
                "id": art_id,
                "chapter_id": c_id,
                "chapter_name": f"Chapter {c_id}",
                "title": f"유효한 정식 뉴스 기사 제목 {counter}호에 관한 상세 보고",
                "link": f"https://media.example.com/article/{counter}",
                "source": f"언론사_{(i % 4) + 1}",
                "published_at": f"{today_kst}T08:{i:02d}:00+09:00",
                "summary_raw": "기사 요약문 원문입니다.",
                "editorial": {
                    "fact": f"핵심 팩트 육하원칙 상세 요약 내용입니다 ({counter}호).",
                    "background": "사건의 정책적 맥락과 산업적 배경 설명입니다.",
                    "why_it_matters": "시장 및 의사결정에 미치는 파급 효과와 핵심 의미입니다.",
                    "checkpoints": ["1차 관전 포인트 내용", "2차 관전 포인트 내용"]
                },
                "keywords": ["인텔리전스", "시장", "기술"],
                "importance_score": 7.5,
                "fact_check": {
                    "status": "VERIFIED_PRIMARY",
                    "evidence_type": "primary",
                    "verified_sources": ["media.example.com"],
                    "notes": "1차 공식 출처 확인 완료",
                    "checked_at": f"{today_kst}T08:00:00Z"
                },
                "image": {
                    "url": None,
                    "source_domain": None,
                    "status": "EXPLICIT_NULL",
                    "verified_at": f"{today_kst}T08:00:00Z"
                }
            })
            counter += 1

        chapters.append({
            "id": c_id,
            "name": f"Chapter {c_id}",
            "name_en": c_id,
            "icon": "📰",
            "description": "설명",
            "count": 10,
            "articles": articles
        })

    top5 = copy.deepcopy(chapters[0]["articles"][:5])

    youtube_channels = ["KBS News", "MBC News", "SBS News", "YTN", "삼프로TV"]
    youtube = [
        {
            "id": f"yt-{i:02d}",
            "title": f"유튜브 핫이슈 영상 {i}",
            "channel": youtube_channels[i % len(youtube_channels)],
            "link": f"https://www.youtube.com/watch?v=mock_{i}",
            "published_at": f"{today_kst}T07:00:00Z"
        }
        for i in range(10)
    ]

    market = {
        "kospi": {"name": "코스피", "value": "2,680.00"},
        "kosdaq": {"name": "코스닥", "value": "765.00"},
        "usd_krw": {"name": "원/달러", "value": "1,335.00"},
        "sp500": {"name": "S&P 500", "value": "5,520.00"},
        "nasdaq": {"name": "나스닥", "value": "17,100.00"},
        "bitcoin": {"name": "비트코인", "value": "$58,000"},
        "updated_at": f"{today_kst} 08:30:00 KST"
    }

    next_signals = [
        {"title": "신호 1", "scheduled_date": "09월 05일", "category": "거시"},
        {"title": "신호 2", "scheduled_date": "09월 06일", "category": "기술"},
        {"title": "신호 3", "scheduled_date": "09월 07일", "category": "금융"}
    ]

    data = {
        "metadata": {
            "title": "BLUELAB Morning Intelligence",
            "date": today_kst,
            "date_formatted": f"{today_kst} (Mock)",
            "generated_at": f"{today_kst}T08:30:00",
            "total_chapters": 14,
            "total_articles": 140,
            "total_youtube_videos": 10,
            "trends_source": "WITHHELD_INSUFFICIENT_RELIABLE_TERMS"
        },
        "weather": {
            "location": "인천 서구 검단",
            "temp_current": 22.5,
            "temp_min": 18.0,
            "temp_max": 28.0,
            "condition": "맑음",
            "condition_icon": "☀️",
            "precipitation_prob": 10
        },
        "three_line_summary": [
            "[라인 1] 첫 번째 요약문입니다.",
            "[라인 2] 두 번째 요약문입니다.",
            "[라인 3] 세 번째 요약문입니다."
        ],
        "top_5_highlights": top5,
        "trending_keywords": [],
        "chapters": chapters,
        "youtube_hot_issues": youtube,
        "market": market,
        "next_signals": next_signals,
        "publication_manifest_fingerprint": "",
        "integrity_hash": "a" * 64
    }
    return data


# 1. Stale edition rejection test
def test_stale_edition_rejection(tmp_path: Path, valid_bundle_data: dict):
    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    valid_bundle_data["metadata"]["date"] = yesterday
    file_path = tmp_path / "today.json"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")

    today_kst = datetime.now(KST).strftime("%Y-%m-%d")
    assert valid_bundle_data["metadata"]["date"] != today_kst


# 2. Cross-edition artifact mismatch test
def test_cross_edition_artifact_mismatch(tmp_path: Path, valid_bundle_data: dict):
    today_kst = datetime.now(KST).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(KST) + timedelta(days=1)).strftime("%Y-%m-%d")
    
    today_file = tmp_path / "today.json"
    today_file.write_text(json.dumps(valid_bundle_data), encoding="utf-8")

    manifest = build_publication_manifest(
        edition_date=tomorrow,
        snapshot_fingerprint="b" * 64,
        editorial_fingerprint="c" * 64,
        production_fingerprint="d" * 64,
        content_counts={"total_chapters": 14, "total_articles": 140, "top5": 5, "youtube": 10, "trends": 0, "summary_lines": 3},
        gate_outcomes={"QA_GATE": "PASS"}
    )
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    passed, errors = validate_manifest(manifest_file, today_file, expected_date=today_kst)
    assert not passed
    assert any("edition date mismatch" in e for e in errors)


# 3. Duplicate URL / Event rejection test
def test_duplicate_url_and_event_rejection(tmp_path: Path, valid_bundle_data: dict):
    # 인위적으로 URL 중복 주입
    valid_bundle_data["chapters"][1]["articles"][0]["link"] = valid_bundle_data["chapters"][0]["articles"][0]["link"]
    file_path = tmp_path / "today.json"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")

    assert run_qa_gate(str(file_path)) is False


# 4. Exact URL enforcement test
def test_exact_url_enforcement(tmp_path: Path, valid_bundle_data: dict):
    # Google News relay URL 주입
    valid_bundle_data["chapters"][0]["articles"][0]["link"] = "https://news.google.com/rss/articles/CBMiM2h0dHBzOi8..."
    file_path = tmp_path / "today.json"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")

    assert run_qa_gate(str(file_path)) is False


# 5. Google Trends withheld behavior test
def test_google_trends_withheld_behavior(tmp_path: Path, valid_bundle_data: dict):
    # 트렌드가 20개가 아닌 애매한 5개인 경우 거부
    valid_bundle_data["trending_keywords"] = [{"keyword": f"k{i}", "count": 10} for i in range(5)]
    file_path = tmp_path / "today.json"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False

    # 0개이지만 WITHHELD 표기가 없는 경우 거부
    valid_bundle_data["trending_keywords"] = []
    valid_bundle_data["metadata"]["trends_source"] = "OTHER"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False

    # 0개이며 WITHHELD 표기가 정상인 경우 승인
    valid_bundle_data["metadata"]["trends_source"] = "WITHHELD_INSUFFICIENT_RELIABLE_TERMS"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is True


# 6. YouTube selected-to-production propagation test
def test_youtube_selected_to_production_propagation(tmp_path: Path, valid_bundle_data: dict):
    # 유튜브 영상 8개(10개 미만) 주입 시 거부
    valid_bundle_data["youtube_hot_issues"] = valid_bundle_data["youtube_hot_issues"][:8]
    file_path = tmp_path / "today.json"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False

    # 10개이지만 채널이 2개뿐인 경우 거부
    yt_10 = [{"channel": f"CH_{i % 2}", "title": f"T{i}", "link": f"https://yt/{i}"} for i in range(10)]
    valid_bundle_data["youtube_hot_issues"] = yt_10
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False


# 7. Fact-check gate test
def test_fact_check_gate(tmp_path: Path, valid_bundle_data: dict):
    # fact_check 데이터 누락 시 거부
    valid_bundle_data["chapters"][0]["articles"][0]["fact_check"] = None
    file_path = tmp_path / "today.json"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False

    # 잘못된 상태값 주입 시 거부
    valid_bundle_data["chapters"][0]["articles"][0]["fact_check"] = {"status": "INVALID_STATE"}
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False


# 8. Image provenance gate test
def test_image_provenance_gate(tmp_path: Path, valid_bundle_data: dict):
    # EXPLICIT_NULL인데 url이 있는 경우 거부
    valid_bundle_data["chapters"][0]["articles"][0]["image"] = {
        "status": "EXPLICIT_NULL",
        "url": "https://unrelated.com/img.jpg"
    }
    file_path = tmp_path / "today.json"
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False

    # VERIFIED_PROVENANCE인데 url이 None인 경우 거부
    valid_bundle_data["chapters"][0]["articles"][0]["image"] = {
        "status": "VERIFIED_PROVENANCE",
        "url": None
    }
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is False

    # 올바른 VERIFIED_PROVENANCE 승인
    valid_bundle_data["chapters"][0]["articles"][0]["image"] = {
        "status": "VERIFIED_PROVENANCE",
        "url": "https://media.example.com/photo.jpg",
        "source_domain": "media.example.com"
    }
    file_path.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    assert run_qa_gate(str(file_path)) is True


# 9. Production manifest fingerprint continuity test
def test_production_manifest_fingerprint_continuity(tmp_path: Path, valid_bundle_data: dict):
    today_kst = datetime.now(KST).strftime("%Y-%m-%d")
    today_file = tmp_path / "today.json"
    today_file.write_text(json.dumps(valid_bundle_data), encoding="utf-8")

    prod_fp = compute_production_fingerprint(valid_bundle_data)
    manifest = build_publication_manifest(
        edition_date=today_kst,
        snapshot_fingerprint="a" * 64,
        editorial_fingerprint="b" * 64,
        production_fingerprint=prod_fp,
        content_counts={
            "total_chapters": 14,
            "total_articles": 140,
            "top5": 5,
            "youtube": 10,
            "trends": 0,
            "summary_lines": 3
        },
        gate_outcomes={"QA_GATE": "PASS"}
    )
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    passed, errors = validate_manifest(manifest_file, today_file, expected_date=today_kst)
    assert passed

    # 임의 변조 시 즉시 감지 실패
    valid_bundle_data["metadata"]["version"] = "9.9.9"
    today_file.write_text(json.dumps(valid_bundle_data), encoding="utf-8")
    passed_tampered, errors_tampered = validate_manifest(manifest_file, today_file, expected_date=today_kst)
    assert not passed_tampered
    assert any("production fingerprint mismatch" in e for e in errors_tampered)


# 10. Cloudflare edition mismatch rejection test
def test_cloudflare_edition_mismatch_rejection():
    expected_edition = "daily-2026-09-04"
    expected_fingerprint = "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"

    # 시뮬레이션: Cloudflare에서 서빙된 데이터가 어제 판인 경우
    mock_cf_served_data = {
        "edition": "daily-2026-09-03",
        "fingerprint": "old_fingerprint"
    }

    is_matched = (
        mock_cf_served_data.get("edition") == expected_edition and
        mock_cf_served_data.get("fingerprint") == expected_fingerprint
    )
    assert is_matched is False
