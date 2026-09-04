"""
run_pipeline.py
BLUELAB Morning Intelligence 종합 자동화 마스터 실행 파이프라인
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pipeline.fetch_and_filter import fetch_all_chapters_raw
from pipeline.scarcity_snapshot_arbiter import arbitrate_and_lock_snapshot
from pipeline.editorial_builder import process_all_editorials
from pipeline.bundle_assembler import assemble_bundle, save_bundle_to_json
from pipeline.google_trends_collector import collect_google_trends_kr
from scripts.qa_gate import run_qa_gate


def main():
    start_time=time.time()
    now_str=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n"+"="*80)
    print(" [BLUELAB Morning Intelligence] 자동 뉴스 브리핑 파이프라인 가동")
    print(f" * 실행 시각: {now_str}")
    print("="*80+"\n")

    try:
        raw_data=fetch_all_chapters_raw()
        snapshot=arbitrate_and_lock_snapshot(raw_data,target_per_chapter=10)
        articles=process_all_editorials(snapshot)
        bundle=assemble_bundle(articles)

        # 합성 기사 키워드는 발행하지 않는다. 공식 Google Trends KR RSS가 정확히 20개일 때만 표시한다.
        trends=collect_google_trends_kr()
        bundle.trending_keywords=trends
        bundle.metadata["trends_source"]=("Google Trends KR official RSS" if len(trends)==20 else "WITHHELD_INSUFFICIENT_RELIABLE_TERMS")

        today_path,archive_path=save_bundle_to_json(bundle)
        qa_passed=run_qa_gate(today_path)
        if not qa_passed:
            print("\n[FATAL ERROR] QA Gate 검증 실패로 인해 배포가 중단되었습니다.")
            sys.exit(1)

        elapsed=time.time()-start_time
        print("\n"+"*"*80)
        print("  PIPELINE QA PASS — PRE-SEND/DEPLOY GATES STILL REQUIRED")
        print(f"  총 14개 챕터 / 140개 기사 / YouTube {len(bundle.youtube_hot_issues)} / Trends {len(bundle.trending_keywords)}")
        print(f"  소요 시간: {elapsed:.2f}초 | 저장 위치: {today_path}")
        print("*"*80+"\n")
    except Exception as e:
        print(f"\n[ERROR] 파이프라인 실행 도중 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__=="__main__":
    main()
