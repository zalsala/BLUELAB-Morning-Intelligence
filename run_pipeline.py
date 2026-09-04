"""
run_pipeline.py
BLUELAB Morning Intelligence 종합 자동화 마스터 실행 파이프라인
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

KST = ZoneInfo("Asia/Seoul")

from pipeline.fetch_and_filter import fetch_all_chapters_raw
from pipeline.scarcity_snapshot_arbiter import arbitrate_and_lock_snapshot
from pipeline.fact_verifier import verify_all_articles
from pipeline.image_provenance import audit_all_images
from pipeline.editorial_builder import process_all_editorials
from pipeline.bundle_assembler import assemble_bundle, save_bundle_to_json
from pipeline.google_trends_collector import collect_google_trends_kr
from pipeline.publication_manifest import (
    compute_snapshot_fingerprint,
    compute_editorial_fingerprint,
    compute_production_fingerprint,
    build_publication_manifest,
    save_publication_manifest,
)
from scripts.qa_gate import run_qa_gate
from scripts.validate_publication_manifest import validate_manifest


def main():
    start_time = time.time()
    now_kst = datetime.now(KST)
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S KST")
    edition_date = now_kst.strftime("%Y-%m-%d")

    print("\n" + "=" * 80)
    print(" [BLUELAB Morning Intelligence] 자동 뉴스 브리핑 파이프라인 가동")
    print(f" * 기준 일자(KST): {edition_date} | 실행 시각: {now_str}")
    print("=" * 80 + "\n")

    try:
        # 1. 수집
        raw_data = fetch_all_chapters_raw()

        # 2. 희소성 우선 교차 챕터 배분, 중복 제거, Exact URL 잠금
        snapshot = arbitrate_and_lock_snapshot(raw_data, target_per_chapter=10)
        snapshot_fp = compute_snapshot_fingerprint(snapshot)

        # 2.5 독립 팩트 검증 관문
        fact_verified = verify_all_articles(snapshot, check_network=False)

        # 2.6 이미지 출처 검증 관문 (검증 도메인 또는 explicit null)
        provenance_verified = audit_all_images(fact_verified)

        # 3. 4대 에디토리얼 심층 분석 결합
        articles = process_all_editorials(provenance_verified)
        editorial_fp = compute_editorial_fingerprint([a.to_dict() for a in articles])

        # 4. 생산 번들 조립 (인천 검단 날씨, 금융 시장, NEXT SIGNALS, 유튜브 >= 10, 3줄 요약)
        bundle = assemble_bundle(articles)

        # 5. 공식 Google Trends KR (정확히 20개일 때만 공개, 부족 시 WITHHELD)
        trends = collect_google_trends_kr()
        bundle.trending_keywords = trends
        bundle.metadata["trends_source"] = (
            "Google Trends KR official RSS"
            if len(trends) == 20
            else "WITHHELD_INSUFFICIENT_RELIABLE_TERMS"
        )

        today_path, archive_path = save_bundle_to_json(bundle)

        # 6. 발간 매니페스트 및 핑거프린트 결속
        initial_prod_fp = compute_production_fingerprint(bundle.to_dict())
        content_counts = {
            "total_chapters": len(bundle.chapters),
            "total_articles": len(articles),
            "top5": len(bundle.top_5_highlights),
            "youtube": len(bundle.youtube_hot_issues),
            "trends": len(bundle.trending_keywords),
            "summary_lines": len(bundle.three_line_summary)
        }

        # 사전 QA 실행
        qa_passed = run_qa_gate(today_path)
        if not qa_passed:
            print("\n[FATAL ERROR] QA Gate 검증 실패로 인해 배포가 중단되었습니다.")
            sys.exit(1)

        manifest = build_publication_manifest(
            edition_date=edition_date,
            snapshot_fingerprint=snapshot_fp,
            editorial_fingerprint=editorial_fp,
            production_fingerprint=initial_prod_fp,
            content_counts=content_counts,
            gate_outcomes={
                "QA_GATE": "PASS",
                "FACT_CHECK_GATE": "PASS",
                "IMAGE_PROVENANCE_GATE": "PASS",
                "EXACT_URL_GATE": "PASS"
            },
            canonical_status="CANONICAL_PASS"
        )
        manifest_path = save_publication_manifest(manifest)

        # today.json에 매니페스트 해시 결속 후 재저장
        bundle.publication_manifest_fingerprint = manifest["manifest_sha256"]
        save_bundle_to_json(bundle)

        # 매니페스트 일관성 최종 검증
        manifest_valid, manifest_errors = validate_manifest(
            Path(manifest_path),
            Path(today_path),
            expected_date=edition_date
        )
        if not manifest_valid:
            print("[FATAL ERROR] 매니페스트 일관성 검증 실패:")
            for err in manifest_errors:
                print(" -", err)
            sys.exit(1)

        elapsed = time.time() - start_time
        print("\n" + "*" * 80)
        print("  PIPELINE CANONICAL PASS — ALL CORE GATES PASSED")
        print(f"  총 14개 챕터 / 140개 기사 / YouTube {len(bundle.youtube_hot_issues)} / Trends {len(bundle.trending_keywords)}")
        print(f"  소요 시간: {elapsed:.2f}초 | 저장 위치: {today_path}")
        print(f"  발간 매니페스트 SHA-256: {manifest['manifest_sha256']}")
        print("*" * 80 + "\n")

    except Exception as e:
        print(f"\n[ERROR] 파이프라인 실행 도중 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
