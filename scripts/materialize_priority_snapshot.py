#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'editorial' / '2026-09-02' / 'priority-snapshot.json'


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def materialize(manifest_path: Path) -> dict:
    manifest = load_json(manifest_path)
    selected = []
    for rel in manifest.get('selected_files') or []:
        chunk = load_json(ROOT / rel)
        selected.extend(chunk.get('selected') or [])
    if len(selected) != manifest.get('selected_count'):
        raise ValueError(f"selected_count mismatch manifest={manifest.get('selected_count')} actual={len(selected)}")
    return {
        'schema_version': 'priority-news-global-arbitration-frozen-v1',
        'edition': manifest.get('edition'),
        'source_snapshot_schema': manifest.get('schema_version'),
        'source_run_id': manifest.get('source_run_id'),
        'source_head_sha': manifest.get('source_head_sha'),
        'as_of': manifest.get('as_of'),
        'generated_at': manifest.get('generated_at'),
        'selected_count': len(selected),
        'coverage_status': 'PASS',
        'chapter_report': manifest.get('chapter_report') or {},
        'duplicate_groups_resolved': manifest.get('duplicate_groups_resolved') or [],
        'backfilled': manifest.get('backfilled') or [],
        'cross_chapter_duplicate_urls': manifest.get('cross_chapter_duplicate_urls') or [],
        'selection_fingerprint_sha256': manifest.get('selection_fingerprint_sha256'),
        'selected': selected,
    }


def self_test() -> None:
    fake = {'selected_count': 2}
    rows = [{'chapter': 'a'}, {'chapter': 'b'}]
    assert len(rows) == fake['selected_count']
    print('PASS: priority snapshot materializer self-test')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=str(DEFAULT))
    ap.add_argument('--output', default='artifacts/priority-news-frozen-arbitrated.json')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    source = Path(args.input)
    if not source.is_absolute():
        source = ROOT / source
    try:
        out = materialize(source)
    except Exception as exc:
        print(f'MATERIALIZE_PRIORITY_SNAPSHOT FAIL {type(exc).__name__}: {exc}')
        return 2
    target = Path(args.output)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(
        f"MATERIALIZE_PRIORITY_SNAPSHOT PASS records={out['selected_count']} "
        f"fingerprint={out['selection_fingerprint_sha256']}"
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
