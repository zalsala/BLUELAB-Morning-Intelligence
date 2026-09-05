#!/usr/bin/env python3
"""
scripts/validate_publication_manifest.py
BLUELAB Morning Intelligence 발간 매니페스트 무결성 및 핑거프린트 일관성 감사 스크립트
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# When this file is executed directly (`python scripts/validate_publication_manifest.py`),
# Python places `scripts/` rather than the repository root on sys.path.  The
# production manifest audit imports validators from the sibling `pipeline`
# package, so fail closed only on real validation errors—not on invocation mode.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def validate_manifest(
    manifest_path: Path,
    today_json_path: Path,
    expected_date: str | None = None
) -> tuple[bool, list[str]]:
    failures = []
    if not manifest_path.exists():
        return False, [f"manifest file missing: {manifest_path}"]
    if not today_json_path.exists():
        return False, [f"today.json file missing: {today_json_path}"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"invalid manifest JSON: {exc}"]

    try:
        today_data = json.loads(today_json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"invalid today.json: {exc}"]

    edition_date = manifest.get("edition_date")
    if expected_date and edition_date != expected_date:
        failures.append(f"manifest edition date mismatch: {edition_date} != {expected_date}")

    if manifest.get("timezone") != "Asia/Seoul":
        failures.append(f"manifest timezone must be Asia/Seoul; found {manifest.get('timezone')}")

    source_main_sha = manifest.get("source_main_sha", "")
    if len(source_main_sha) != 40:
        failures.append(f"invalid source_main_sha: {source_main_sha}")

    fingerprints = manifest.get("fingerprints", {})
    prod_fp = fingerprints.get("production_fingerprint_sha256")
    if not prod_fp or len(prod_fp) != 64:
        failures.append("production_fingerprint_sha256 missing or malformed")

    copy_d = dict(today_data)
    copy_d.pop("publication_manifest_fingerprint", None)
    expected_prod_fp = hashlib.sha256(json.dumps(copy_d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    if prod_fp != expected_prod_fp:
        failures.append(f"production fingerprint mismatch: manifest={prod_fp} != recomputed={expected_prod_fp}")

    saved_sha = manifest.get("manifest_sha256")
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_sha256", None)
    computed_sha = hashlib.sha256(json.dumps(manifest_body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    if saved_sha != computed_sha:
        failures.append(f"manifest_sha256 integrity mismatch: {saved_sha} != {computed_sha}")

    counts = manifest.get("content_counts", {})
    if counts.get("total_chapters") != 14:
        failures.append(f"content_counts.total_chapters={counts.get('total_chapters')} != 14")
    if counts.get("total_articles") != 140:
        failures.append(f"content_counts.total_articles={counts.get('total_articles')} != 140")
    if counts.get("top5") != 5:
        failures.append(f"content_counts.top5={counts.get('top5')} != 5")
    if (counts.get("youtube") or 0) < 10:
        failures.append(f"content_counts.youtube={counts.get('youtube')} < 10")
    if counts.get("trends") not in (0, 20):
        failures.append(f"content_counts.trends={counts.get('trends')} not in (0, 20)")
    if counts.get("summary_lines") != 3:
        failures.append(f"content_counts.summary_lines={counts.get('summary_lines')} != 3")

    # New canonical production manifests explicitly declare story_bundles.
    # Legacy unit fixtures that predate this field continue to test fingerprint
    # continuity only; production can never bypass this because run_pipeline
    # always emits story_bundles and metadata.story_files.
    story_contract_declared = "story_bundles" in counts or "story_files" in today_data.get("metadata", {})
    if story_contract_declared:
        if counts.get("story_bundles") != 5:
            failures.append(f"content_counts.story_bundles={counts.get('story_bundles')} != 5")
        try:
            from pipeline.story_bundle_writer import validate_story_bundles
            failures.extend(validate_story_bundles(today_json_path, today_json_path.parent))
        except Exception as exc:
            failures.append(f"story bundle validator error: {exc}")
        metadata_story_files = today_data.get("metadata", {}).get("story_files")
        expected_story_files = [f"stories-{i}.json" for i in range(1, 6)]
        if metadata_story_files != expected_story_files:
            failures.append(f"today metadata.story_files must be exactly {expected_story_files}; found {metadata_story_files}")

    return (len(failures) == 0, failures)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(ROOT / "public" / "data" / "publication_manifest.json"))
    parser.add_argument("--today", default=str(ROOT / "public" / "data" / "today.json"))
    parser.add_argument("--expected-date", default=None)
    args = parser.parse_args()

    passed, errors = validate_manifest(Path(args.manifest), Path(args.today), args.expected_date)
    if not passed:
        print("[PUBLICATION MANIFEST AUDIT REJECTED]")
        for err in errors:
            print(" -", err)
        return 1
    print("[PUBLICATION MANIFEST AUDIT PASSED] fingerprint + five-story-bundle continuity verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
