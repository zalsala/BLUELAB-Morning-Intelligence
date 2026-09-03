"""
scripts/qa_gate.py
BLUELAB Morning Intelligence 엄격한 품질 검사기 (QA Gate)
- 14개 챕터 엄수
- 140개 기사 엄수 (각 챕터 10개)
- 중복 0건
- 4대 에디토리얼(Fact/Background/Why/Checkpoints) 완성도 100%
- 인천 검단 날씨 / TOP5 / 트렌드 20개 / 무결성 해시 검증
- 실패 시 절대 배포 차단 (exit 1), 통과 시 (exit 0)
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import json
import hashlib
from typing import Dict, Any, List

EXPECTED_CHAPTER_COUNT = 14
EXPECTED_ARTICLES_PER_CHAPTER = 10
EXPECTED_TOTAL_ARTICLES = 140
EXPECTED_TRENDING_COUNT = 20
EXPECTED_TOP5_COUNT = 5


def run_qa_gate(json_path: str = "public/data/today.json") -> bool:
    print("=" * 75)
    print(" [QA GATE] BLUELAB Morning Intelligence 엄격 품질 검사 시작")
    print("=" * 75)

    failures: List[str] = []

    # Gate 1: 파일 존재 및 JSON 파싱 검증
    print(" [Gate 1] JSON 파일 무결성 및 구조 검사...", end=" ")
    if not os.path.exists(json_path):
        failures.append(f"Gate 1 실패: 파일이 존재하지 않습니다 ({json_path})")
        print("[FAIL]")
        _print_report(failures)
        return False

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print("[PASS]")
    except Exception as e:
        failures.append(f"Gate 1 실패: JSON 파싱 오류 ({e})")
        print("[FAIL]")
        _print_report(failures)
        return False

    # Gate 2: 14개 챕터 구조 검증
    print(" [Gate 2] 14개 챕터 구조 검사...", end=" ")
    chapters = data.get("chapters", [])
    if len(chapters) != EXPECTED_CHAPTER_COUNT:
        failures.append(f"Gate 2 실패: 챕터 수가 {len(chapters)}개입니다 (기대값: {EXPECTED_CHAPTER_COUNT}개)")
        print("[FAIL]")
    else:
        print("[PASS] (14개 챕터 완벽 일치)")

    # Gate 3: 기사 수량 (각 10개, 총 140개) 검증
    print(" [Gate 3] 기사 수량 쿼터 검사 (챕터당 10개, 총 140개)...", end=" ")
    total_articles = 0
    chapter_count_errors = []
    
    for ch in chapters:
        c_name = ch.get("name", "Unknown")
        c_arts = ch.get("articles", [])
        c_len = len(c_arts)
        total_articles += c_len
        if c_len != EXPECTED_ARTICLES_PER_CHAPTER:
            chapter_count_errors.append(f"'{c_name}' 챕터 기사 수량: {c_len}개 (필요: {EXPECTED_ARTICLES_PER_CHAPTER}개)")

    if total_articles != EXPECTED_TOTAL_ARTICLES or chapter_count_errors:
        err_msg = f"Gate 3 실패: 총 기사 수가 {total_articles}개입니다 (기대값: {EXPECTED_TOTAL_ARTICLES}개)."
        if chapter_count_errors:
            err_msg += " 세부 불일치: " + ", ".join(chapter_count_errors)
        failures.append(err_msg)
        print("[FAIL]")
    else:
        print("[PASS] (총 140개 기사 쿼터 100% 충족)")

    # Gate 4: 중복 기사 0건 검증 (ID / URL / 제목 고유성)
    print(" [Gate 4] 중복 기사 0건 검증 (ID / URL / 제목 고유성)...", end=" ")
    seen_ids = set()
    seen_urls = set()
    seen_titles = set()
    duplicate_errors = []

    for ch in chapters:
        for art in ch.get("articles", []):
            a_id = art.get("id", "")
            url = art.get("link", "")
            title = art.get("title", "")

            if not a_id or a_id in seen_ids:
                duplicate_errors.append(f"기사 ID 중복/누락: {a_id}")
            seen_ids.add(a_id)

            if not url or url in seen_urls:
                duplicate_errors.append(f"기사 URL 중복/누락: {url[:30]}...")
            seen_urls.add(url)

            if not title or title in seen_titles:
                duplicate_errors.append(f"기사 제목 중복/누락: {title[:20]}...")
            seen_titles.add(title)

    if duplicate_errors:
        failures.append(f"Gate 4 실패: 총 {len(duplicate_errors)}건의 중복 또는 ID 누락 발견: {duplicate_errors[:3]}")
        print("[FAIL]")
    else:
        print("[PASS] (중복 0건 완벽 검증)")

    # Gate 5: 4대 에디토리얼 심층 분석 필드 완전성 검증
    print(" [Gate 5] 4대 에디토리얼 심층 분석 필드 완전성 검증...", end=" ")
    editorial_errors = []
    
    for ch in chapters:
        for art in ch.get("articles", []):
            ed = art.get("editorial", {})
            fact = ed.get("fact", "").strip()
            bg = ed.get("background", "").strip()
            why = ed.get("why_it_matters", "").strip()
            chk = ed.get("checkpoints", [])

            if not fact or len(fact) < 10:
                editorial_errors.append(f"기사 '{art.get('title')[:15]}...'의 Fact 누락 또는 미흡")
            if not bg or len(bg) < 10:
                editorial_errors.append(f"기사 '{art.get('title')[:15]}...'의 Background 누락 또는 미흡")
            if not why or len(why) < 10:
                editorial_errors.append(f"기사 '{art.get('title')[:15]}...'의 Why It Matters 누락 또는 미흡")
            if not chk or len(chk) < 2:
                editorial_errors.append(f"기사 '{art.get('title')[:15]}...'의 Checkpoints 항목 부족 (최소 2개)")

    if editorial_errors:
        failures.append(f"Gate 5 실패: {len(editorial_errors)}건의 에디토리얼 데이터 결함 발견")
        print("[FAIL]")
    else:
        print("[PASS] (140개 전 기사 4대 에디토리얼 100% 충족)")

    # Gate 6: 날씨, TOP5, 트렌드 20개, 3줄 요약, 무결성 해시 검증
    print(" [Gate 6] 인천 검단 날씨, TOP5, 트렌드 20개, 무결성 해시 검증...", end=" ")
    extra_errors = []

    weather = data.get("weather", {})
    if not weather or "인천 서구 검단" not in weather.get("location", "") or "temp_current" not in weather:
        extra_errors.append("인천 서구 검단 날씨 데이터 누락 또는 불완전")

    top5 = data.get("top_5_highlights", [])
    if len(top5) != EXPECTED_TOP5_COUNT:
        extra_errors.append(f"TOP 5 하이라이트 수량이 {len(top5)}개입니다 (기대값: {EXPECTED_TOP5_COUNT}개)")

    trending = data.get("trending_keywords", [])
    if len(trending) != EXPECTED_TRENDING_COUNT:
        extra_errors.append(f"트렌드 키워드 수량이 {len(trending)}개입니다 (기대값: {EXPECTED_TRENDING_COUNT}개)")

    three_lines = data.get("three_line_summary", [])
    if len(three_lines) != 3:
        extra_errors.append(f"3줄 총평 요약 줄 수가 {len(three_lines)}줄입니다 (기대값: 3줄)")

    integrity_hash = data.get("integrity_hash", "")
    if not integrity_hash or len(integrity_hash) < 32:
        extra_errors.append("무결성 해시(integrity_hash) 누락 또는 비정상")

    if extra_errors:
        failures.append(f"Gate 6 실패: " + "; ".join(extra_errors))
        print("[FAIL]")
    else:
        print("[PASS] (날씨·TOP5·트렌드·3줄요약·해시 100% 정상)")

    # 최종 결과 판정
    print("-" * 75)
    if failures:
        _print_report(failures)
        print(" [QA GATE REJECTED] 배포가 차단되었습니다. 위 오류를 수정해야 합니다.")
        print("=" * 75)
        return False
    else:
        print(" [QA GATE PASSED] 모든 6대 품질 검사 관문을 완벽히 통과했습니다!")
        print(f"    - 총 챕터: {len(chapters)}개")
        print(f"    - 총 기사: {total_articles}개 (중복 0건, 에디토리얼 완성도 100%)")
        print(f"    - 인천 검단 날씨: {weather.get('condition_icon')} {weather.get('condition')} ({weather.get('temp_current')}℃)")
        print(f"    - 무결성 잠금 해시: {integrity_hash}")
        print("=" * 75)
        return True


def _print_report(failures: List[str]):
    print("\n [발견된 결함 리포트]")
    for idx, f in enumerate(failures, 1):
        print(f"  {idx}. {f}")
    print()


if __name__ == "__main__":
    target_file = sys.argv[1] if len(sys.argv) > 1 else "public/data/today.json"
    passed = run_qa_gate(target_file)
    if not passed:
        sys.exit(1)
    else:
        sys.exit(0)
