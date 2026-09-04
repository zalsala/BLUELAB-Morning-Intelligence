"""
pipeline/youtube_collector.py
검증된 공식 YouTube 채널 RSS를 이용한 최신 영상 수집 모듈.
config/youtube-signals.json을 단일 정책 소스로 사용한다.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import feedparser
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "youtube-signals.json"
REQUEST_TIMEOUT = 5
RSS_RETRY_COUNT = 2
RSS_RETRY_BACKOFF_SECONDS = 1.0


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _entry_datetime(entry) -> dt.datetime | None:
    parsed = getattr(entry, "published_parsed", None)
    if parsed:
        return dt.datetime(*parsed[:6], tzinfo=dt.timezone.utc)
    raw = getattr(entry, "published", "") or getattr(entry, "updated", "")
    if raw:
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except Exception:
            return None
    return None


def _feed_urls(channel_id: str) -> List[str]:
    """Return official YouTube RSS variants for the same verified channel.

    YouTube's channel_id feed has shown intermittent 404/500 failures. The
    uploads playlist is the canonical per-channel uploads playlist obtained by
    replacing the leading ``UC`` with ``UU`` and provides the same official
    source without relaxing source provenance.
    """
    urls = [f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"]
    if channel_id.startswith("UC") and len(channel_id) > 2:
        uploads_playlist_id = "UU" + channel_id[2:]
        urls.append(
            f"https://www.youtube.com/feeds/videos.xml?playlist_id={uploads_playlist_id}"
        )
    return urls


def _fetch_channel_feed(session: requests.Session, channel_id: str) -> bytes:
    """Fetch an official channel feed with bounded retry and uploads fallback."""
    errors: List[str] = []
    for feed_url in _feed_urls(channel_id):
        for attempt in range(1, RSS_RETRY_COUNT + 1):
            try:
                response = session.get(feed_url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                if not response.content:
                    raise ValueError("empty RSS response")
                return response.content
            except Exception as exc:
                errors.append(
                    f"{feed_url} attempt={attempt}/{RSS_RETRY_COUNT}: "
                    f"{type(exc).__name__}: {exc}"
                )
                if attempt < RSS_RETRY_COUNT:
                    time.sleep(RSS_RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(" | ".join(errors))


def collect_youtube_hot_issues(limit_per_channel: int | None = None) -> List[Dict[str, Any]]:
    """정책에 등록된 공식 채널에서 최신 영상을 수집하고 diversity/freshness를 적용한다."""
    policy = load_policy()
    channels = policy.get("channels", [])
    target = int(policy.get("target", 10))
    max_age_days = int(policy.get("max_age_days", 3))
    max_per_channel = int(policy.get("max_per_channel", 3))
    minimum_unique_channels = int(policy.get("minimum_unique_channels", 4))
    per_channel = limit_per_channel or max_per_channel
    now = dt.datetime.now(dt.timezone.utc)

    print("  └─ 검증된 공식 YouTube 채널 RSS 수집 중...")
    candidates: List[Dict[str, Any]] = []

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; BLUELAB-Morning-Intelligence/1.0; +https://github.com/zalsala/BLUELAB-Morning-Intelligence)",
        "Accept": "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    })

    for ch in channels:
        try:
            feed_content = _fetch_channel_feed(session, ch["channel_id"])
            feed = feedparser.parse(feed_content)
            accepted = 0
            for entry in feed.entries:
                if accepted >= per_channel:
                    break
                published_dt = _entry_datetime(entry)
                if not published_dt:
                    continue
                age_days = (now - published_dt).total_seconds() / 86400
                if age_days < -0.25 or age_days > max_age_days:
                    continue

                vid_id = getattr(entry, "yt_videoid", "")
                if not vid_id:
                    link = getattr(entry, "link", "")
                    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", link)
                    if m:
                        vid_id = m.group(1)
                if not vid_id:
                    continue

                title = clean_text(getattr(entry, "title", ""))
                if not title:
                    continue
                summary = clean_text(getattr(entry, "summary", ""))[:180]
                candidates.append({
                    "id": vid_id,
                    "title": title,
                    "channel": ch["name"],
                    "category": "공식 뉴스/연구 채널",
                    "video_url": f"https://www.youtube.com/watch?v={vid_id}",
                    "embed_url": f"https://www.youtube.com/embed/{vid_id}",
                    "thumbnail": f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
                    "published_at": published_dt.date().isoformat(),
                    "summary": summary or f"{ch['name']} 공식 채널의 최신 영상입니다.",
                    "source_tier": ch.get("tier"),
                    "source_id": ch.get("id"),
                })
                accepted += 1
        except Exception as exc:
            print(f"    [!] YouTube 채널({ch.get('name')}) 수집 실패: {type(exc).__name__}: {exc}")

    dedup: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        dedup.setdefault(item["id"], item)
    ordered = sorted(dedup.values(), key=lambda x: x["published_at"], reverse=True)

    selected: List[Dict[str, Any]] = []
    channel_counts: Dict[str, int] = {}
    for item in ordered:
        channel = item["channel"]
        if channel_counts.get(channel, 0) >= max_per_channel:
            continue
        selected.append(item)
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
        if len(selected) >= target:
            break

    unique_channels = len({x["channel"] for x in selected})
    status = "PASS" if len(selected) >= target and unique_channels >= minimum_unique_channels else "FAIL"
    print(
        f"  └─ YouTube 정책 검증: selected={len(selected)}/{target}, "
        f"unique_channels={unique_channels}/{minimum_unique_channels}, status={status}"
    )
    return selected


if __name__ == "__main__":
    vids = collect_youtube_hot_issues()
    print("Collected videos:", len(vids))
