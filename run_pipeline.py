"""
run_pipeline.py
BLUELAB Morning Intelligence 종합 자동화 마스터 실행 파이프라인
"""
from __future__ import annotations

import sys
import os
import time
from datetime import datetime

# Windows 콘솔 UTF-8 출력 보장
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pipeline.fetch_and_filter import fetch_all_chapters_raw
from pipeline.snapshot_arbiter import arbitrate_and_lock_snapshot
from pipeline.editorial_builder import process_all_editorials
from pipeline.bundle_assembler import assemble_bundle, save_bundle_to_json
from scripts.qa_gate import run_qa_gate


def main():
    start_time = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 80)
    print(" [BLUELAB Morning Intelligence] 자동 뉴스 브리핑 파이프라인 가동")
    print(f" * 실행 시각: {now_str}")
    print("=" * 80 + "\n")

    try:
        # Step 1: 14개 챕터 RSS 수집 및 품질 필터링
        raw_data = fetch_all_chapters_raw()

        # Step 2: 중복 제거, 스코어링 및 정확히 140개 기사 선별 + 해시 잠금
        snapshot = arbitrate_and_lock_snapshot(raw_data, target_per_chapter=10)

        # Step 3: 기사별 4대 심층 에디토리얼 구축
        articles = process_all_editorials(snapshot)

        # Step 4: 인천 검단 날씨, TOP5, 20대 트렌드, 3줄 요약 통합 번들 조립 및 JSON 저장
        bundle = assemble_bundle(articles)
        today_path, archive_path = save_bundle_to_json(bundle)

        # Step 5: 엄격한 QA Gate 검증 (140개, 중복 0건, 에디토리얼 100%, 날씨/TOP5/해시 일치)
        qa_passed = run_qa_gate(today_path)

        if not qa_passed:
            print("\n[FATAL ERROR] QA Gate 검증 실패로 인해 배포가 중단되었습니다.")
            sys.exit(1)

        elapsed = time.time() - start_time
        print("\n" + "*" * 80)
        print("  오늘 브리핑 업데이트 완료 — QA PASS")
        print(f"  총 14개 챕터 / 140개 인텔리전스 기사 / 인천 검단 날씨 / TOP5 / 20대 트렌드")
        print(f"  소요 시간: {elapsed:.2f}초 | 저장 위치: {today_path}")
        print("*" * 80 + "\n")

    except Exception as e:
        print(f"\n[ERROR] 파이프라인 실행 도중 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
