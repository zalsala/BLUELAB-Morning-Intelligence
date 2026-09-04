from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pipeline.youtube_collector import _cached_verified_candidates, _select_videos, load_policy


def _write_cache(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"youtube_hot_issues": rows}, ensure_ascii=False), encoding="utf-8")


def _row(video_id: str, channel: str, source_id: str, published_at: str) -> dict:
    return {
        "id": video_id,
        "title": f"검증 영상 {video_id}",
        "channel": channel,
        "category": "공식 뉴스/연구 채널",
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "embed_url": f"https://www.youtube.com/embed/{video_id}",
        "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "published_at": published_at,
        "summary": "이전에 성공적으로 발행된 검증 영상",
        "source_id": source_id,
        "source_tier": 2,
    }


def test_verified_cache_can_fill_target_with_four_policy_channels(tmp_path: Path):
    policy = load_policy()
    now = dt.datetime.now(dt.timezone.utc)
    day = now.date().isoformat()
    channels = policy["channels"][:4]
    rows = []
    for i in range(10):
        ch = channels[i % 4]
        rows.append(_row(f"cacheVid{i:02d}", ch["name"], ch["id"], day))

    cache = tmp_path / "today.json"
    _write_cache(cache, rows)
    candidates = _cached_verified_candidates(policy, now, cache)
    selected = _select_videos(candidates, target=10, max_per_channel=3)

    assert len(selected) == 10
    assert len({x["channel"] for x in selected}) == 4
    assert all(x["retrieval_mode"] == "cached_verified" for x in selected)


def test_stale_cached_video_is_rejected(tmp_path: Path):
    policy = load_policy()
    now = dt.datetime.now(dt.timezone.utc)
    stale = (now - dt.timedelta(days=4)).date().isoformat()
    ch = policy["channels"][0]
    cache = tmp_path / "today.json"
    _write_cache(cache, [_row("staleVid01", ch["name"], ch["id"], stale)])

    assert _cached_verified_candidates(policy, now, cache) == []


def test_unconfigured_or_mismatched_channel_is_rejected(tmp_path: Path):
    policy = load_policy()
    now = dt.datetime.now(dt.timezone.utc)
    day = now.date().isoformat()
    cache = tmp_path / "today.json"
    rows = [
        _row("unknown01", "Unknown Channel", "unknown-source", day),
        _row("mismatch01", "Wrong Name", policy["channels"][0]["id"], day),
    ]
    _write_cache(cache, rows)

    assert _cached_verified_candidates(policy, now, cache) == []
