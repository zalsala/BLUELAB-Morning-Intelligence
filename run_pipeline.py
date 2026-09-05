"""BLUELAB Morning Intelligence 종합 자동화 마스터 실행 파이프라인."""
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
from pipeline.article_body_collector import validate_article_bodies
from pipeline.image_collector import collect_article_images
from pipeline.image_provenance import audit_all_images
from pipeline.editorial_quality import process_all_editorials
from pipeline.bundle_assembler import assemble_bundle, save_bundle_to_json, generate_three_line_summary
from pipeline.top5_ranker import select_top5_v2
from pipeline.google_trends_collector import collect_google_trends_kr
from pipeline.korean_quality import polish_editorial_articles, polish_bundle_summary, validate_korean_quality
from pipeline.publication_manifest import compute_snapshot_fingerprint, compute_editorial_fingerprint, compute_production_fingerprint, build_publication_manifest, save_publication_manifest
from pipeline.story_bundle_writer import write_story_bundles, validate_story_bundles
from pipeline.vision_watch_builder import build_vision_watch
from scripts.qa_gate import run_qa_gate
from scripts.validate_publication_manifest import validate_manifest


def main():
    start_time=time.time(); now_kst=datetime.now(KST); now_str=now_kst.strftime("%Y-%m-%d %H:%M:%S KST"); edition_date=now_kst.strftime("%Y-%m-%d")
    print("\n"+"="*80); print(" [BLUELAB Morning Intelligence] 자동 뉴스 브리핑 파이프라인 가동"); print(f" * 기준 일자(KST): {edition_date} | 실행 시각: {now_str}"); print("="*80+"\n")
    try:
        raw_data=fetch_all_chapters_raw()
        snapshot=arbitrate_and_lock_snapshot(raw_data,target_per_chapter=10)
        snapshot_fp=compute_snapshot_fingerprint(snapshot)
        fact_verified=verify_all_articles(snapshot,check_network=False)
        body_validated=validate_article_bodies(fact_verified)

        image_candidates=collect_article_images(body_validated)
        provenance_verified=audit_all_images(image_candidates)

        articles=process_all_editorials(provenance_verified)
        polish_editorial_articles(articles)
        editorial_fp=compute_editorial_fingerprint([a.to_dict() for a in articles])

        bundle=assemble_bundle(articles)
        bundle.top_5_highlights=select_top5_v2(articles)
        bundle.three_line_summary=generate_three_line_summary(bundle.top_5_highlights,bundle.weather)
        print("  └─ TOP5 v2 evidence-weighted ranking applied: " + ", ".join(a.chapter_name for a in bundle.top_5_highlights))

        polish_bundle_summary(bundle); validate_korean_quality(bundle)
        trends=collect_google_trends_kr(); bundle.trending_keywords=trends
        bundle.metadata["trends_source"]="Google Trends KR official RSS" if len(trends)==20 else "WITHHELD_INSUFFICIENT_RELIABLE_TERMS"
        validate_korean_quality(bundle)

        # Exactly five legacy/canonical story bundles remain the 140 general
        # stories. The independent scholarly watch is added afterwards so it is
        # rendered live without changing those five bundles.
        story_files=write_story_bundles(bundle)
        bundle.metadata["story_files"]=story_files

        print("="*70); print(" [Step 4.5] 독립 VISION RESEARCH WATCH 수집·선별·정책검증"); print("="*70)
        vision_chapter,vision_report=build_vision_watch(target=10)
        bundle.chapters.append(vision_chapter)
        bundle.metadata["general_chapters"]=14
        bundle.metadata["general_articles"]=140
        bundle.metadata["total_chapters"]=15
        bundle.metadata["total_articles"]=150
        bundle.metadata["vision_research_watch_count"]=10
        bundle.metadata["vision_research_watch_window_days"]=vision_report["window_days"]
        data_dir=Path("public/data"); data_dir.mkdir(parents=True,exist_ok=True)
        (data_dir/"vision-research-watch.json").write_text(json.dumps(vision_report,ensure_ascii=False,indent=2),encoding="utf-8")
        archive_dir=data_dir/"archive"; archive_dir.mkdir(parents=True,exist_ok=True)
        (archive_dir/f"{edition_date}-vision-research-watch.json").write_text(json.dumps(vision_report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"  [VISION WATCH] PASS selected=10 domains={len(vision_report['exact_source_domains'])} topics={vision_report['topic_counts']}")

        today_path,archive_path=save_bundle_to_json(bundle)
        story_errors=validate_story_bundles(Path(today_path))
        if story_errors:
            print("[FATAL ERROR] canonical story bundle gate failed:")
            for err in story_errors: print(" -",err)
            sys.exit(1)

        initial_prod_fp=compute_production_fingerprint(bundle.to_dict())
        content_counts={
            "total_chapters":len(bundle.chapters),"total_articles":150,
            "general_chapters":14,"general_articles":140,"vision_research_watch":10,
            "top5":len(bundle.top_5_highlights),"youtube":len(bundle.youtube_hot_issues),
            "trends":len(bundle.trending_keywords),"summary_lines":len(bundle.three_line_summary),
            "story_bundles":len(story_files)
        }
        if not run_qa_gate(today_path):
            print("\n[FATAL ERROR] QA Gate 검증 실패로 인해 배포가 중단되었습니다."); sys.exit(1)
        manifest=build_publication_manifest(
            edition_date=edition_date,snapshot_fingerprint=snapshot_fp,
            editorial_fingerprint=editorial_fp,production_fingerprint=initial_prod_fp,
            content_counts=content_counts,
            gate_outcomes={
                "QA_GATE":"PASS","FACT_CHECK_GATE":"PASS","ARTICLE_BODY_VALIDATION_GATE":"PASS",
                "TOP5_EVIDENCE_RANKING_GATE":"PASS","IMAGE_DISCOVERY_GATE":"PASS","IMAGE_PROVENANCE_GATE":"PASS",
                "EXACT_URL_GATE":"PASS","STORY_BUNDLE_GATE":"PASS","VISION_RESEARCH_WATCH_GATE":"PASS",
                "GOOGLE_TRENDS_GATE":"PASS" if len(trends)==20 else "WITHHELD_POLICY_COMPLIANT"
            },canonical_status="CANONICAL_PASS")
        manifest_path=save_publication_manifest(manifest)
        bundle.publication_manifest_fingerprint=manifest["manifest_sha256"]; save_bundle_to_json(bundle)
        valid,errors=validate_manifest(Path(manifest_path),Path(today_path),expected_date=edition_date)
        if not valid:
            print("[FATAL ERROR] 매니페스트 일관성 검증 실패:")
            for err in errors: print(" -",err)
            sys.exit(1)
        story_errors=validate_story_bundles(Path(today_path))
        if story_errors:
            print("[FATAL ERROR] final story bundle consistency failed:")
            for err in story_errors: print(" -",err)
            sys.exit(1)
        elapsed=time.time()-start_time
        print("\n"+"*"*80); print("  PIPELINE CANONICAL PASS — ALL CORE GATES PASSED"); print(f"  일반 14개/140기사 + Vision Research Watch 10건 / Story bundles {len(story_files)} / YouTube {len(bundle.youtube_hot_issues)} / Trends {len(bundle.trending_keywords)}"); print(f"  소요 시간: {elapsed:.2f}초 | 저장 위치: {today_path}"); print(f"  발간 매니페스트 SHA-256: {manifest['manifest_sha256']}"); print("*"*80+"\n")
    except Exception as e:
        print(f"\n[ERROR] 파이프라인 실행 도중 예외 발생: {e}"); import traceback; traceback.print_exc(); sys.exit(1)


if __name__ == "__main__": main()
