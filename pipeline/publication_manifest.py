"""
pipeline/publication_manifest.py
BLUELAB Morning Intelligence 발간 정본 매니페스트 (Publication Manifest) 생성 및 검증 모듈

PRODUCTION IDENTITY:
edition
edition_date
timezone
source main SHA
release SHA
snapshot fingerprint
editorial fingerprint
production fingerprint
content counts
individual gate outcomes
canonical status
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[1]
BASELINE_MAIN_SHA = "44d568f03028ce4b35deda7660f69deeb92d3e70"


def get_git_sha() -> str:
    """현재 작업 트리의 Git 커밋 SHA 반환"""
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown-git-sha"


def compute_snapshot_fingerprint(snapshot_articles: List[Dict[str, Any]]) -> str:
    """선별 기사의 불변 정체성 해시 (chapter_id|link 순 정렬)"""
    rows = [f"{a.get('chapter_id','')}|{(a.get('link') or '').strip()}" for a in snapshot_articles]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def compute_editorial_fingerprint(articles: List[Dict[str, Any]]) -> str:
    """에디토리얼 분석 데이터의 정체성 해시"""
    rows = []
    for a in articles:
        ed = a.get("editorial") or {}
        fact = (ed.get("fact") or "")[:40]
        bg = (ed.get("background") or "")[:40]
        rows.append(f"{a.get('id','')}|{fact}|{bg}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def compute_production_fingerprint(bundle_dict: Dict[str, Any]) -> str:
    """생성된 today.json 정본의 정체성 해시 (manifest_fingerprint 필드 제외 정규화)"""
    copy_d = dict(bundle_dict)
    copy_d.pop("publication_manifest_fingerprint", None)
    canonical_json = json.dumps(copy_d, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def build_publication_manifest(
    edition_date: str,
    snapshot_fingerprint: str,
    editorial_fingerprint: str,
    production_fingerprint: str,
    content_counts: Dict[str, int],
    gate_outcomes: Dict[str, str],
    canonical_status: str = "PENDING",
    release_sha: Optional[str] = None
) -> Dict[str, Any]:
    """공식 발간 매니페스트 데이터 구조체 생성"""
    rel_sha = release_sha or get_git_sha()
    manifest_data = {
        "schema_version": "publication-manifest-v1",
        "edition": f"daily-{edition_date}",
        "edition_date": edition_date,
        "timezone": "Asia/Seoul",
        "source_main_sha": BASELINE_MAIN_SHA,
        "release_sha": rel_sha,
        "fingerprints": {
            "snapshot_fingerprint_sha256": snapshot_fingerprint,
            "editorial_fingerprint_sha256": editorial_fingerprint,
            "production_fingerprint_sha256": production_fingerprint
        },
        "content_counts": content_counts,
        "individual_gate_outcomes": gate_outcomes,
        "canonical_status": canonical_status,
        "created_at": datetime.now(KST).isoformat()
    }

    body_bytes = json.dumps(manifest_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest_sha = hashlib.sha256(body_bytes).hexdigest()
    manifest_data["manifest_sha256"] = manifest_sha
    return manifest_data


def save_publication_manifest(manifest: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
    """public/data/publication_manifest.json 에 저장"""
    target = output_path or (ROOT / "public" / "data" / "publication_manifest.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [매니페스트 저장 완료] {target} (SHA256: {manifest.get('manifest_sha256','')[:16]}...)")
    return target
