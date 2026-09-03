"""
pipeline/youtube_collector.py
주요 방송사 및 경제/시사/테크 유튜브 채널 실시간 핫이슈 영상 수집 모듈
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import html
import datetime
import feedparser
from typing import List, Dict, Any

YOUTUBE_CHANNELS = [
    {"name": "KBS News", "channel_id": "UCcQTRi69dsVYHN3exePtZ1A", "category": "종합뉴스"},
    {"name": "MBC News", "channel_id": "UCF4WxDo3inmxP-Y59wXDsFw", "category": "종합뉴스"},
    {"name": "SBS News", "channel_id": "UCkinYTS9IHqOEwR1Sze2JTw", "category": "종합뉴스"},
    {"name": "YTN", "channel_id": "UChlgI3UHCOnwUGzWzbJ3H5w", "category": "24시간속보"},
    {"name": "JTBC News", "channel_id": "UCsU-I-vHLiaMfV_ceaYz5rQ", "category": "심층보도"},
    {"name": "연합뉴스TV", "channel_id": "UCw9d52i_U-qB4r7K4jM5Qbg", "category": "속보/경제"},
    {"name": "한국경제TV", "channel_id": "UCWskgJvUoxft3GcwR_LzYwQ", "category": "경제/증시"},
    {"name": "삼프로TV", "channel_id": "UCO8t3Pz83_k2Q9w8JqP4z7A", "category": "경제/금융"},
    {"name": "슈카월드", "channel_id": "UCbSgKzS1D977e2E_j0R5K4w", "category": "시사/이슈"},
    {"name": "BBC News 코리아", "channel_id": "UCU_vFqZf1r1zD3bXjW6m2cA", "category": "국제정세"},
]

def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()

def collect_youtube_hot_issues(limit_per_channel: int = 2) -> List[Dict[str, Any]]:
    """유튜브 실시간 핫이슈 영상 수집"""
    print("  └─ 유튜브 실시간 주요 방송/경제 채널 핫이슈 피드 수집 중...")
    results = []

    for ch in YOUTUBE_CHANNELS:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            d = feedparser.parse(feed_url)
            for entry in d.entries[:limit_per_channel]:
                vid_id = getattr(entry, "yt_videoid", "")
                if not vid_id and hasattr(entry, "link"):
                    m = re.search(r"v=([a-zA-Z0-9_-]+)", entry.link)
                    if m:
                        vid_id = m.group(1)
                
                if not vid_id:
                    continue

                title = clean_text(getattr(entry, "title", ""))
                published = getattr(entry, "published", "")
                summary = clean_text(getattr(entry, "summary", ""))[:120]

                # 고화질 썸네일 URL
                thumbnail_url = f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"

                results.append({
                    "id": vid_id,
                    "title": title,
                    "channel": ch["name"],
                    "category": ch["category"],
                    "video_url": f"https://www.youtube.com/watch?v={vid_id}",
                    "embed_url": f"https://www.youtube.com/embed/{vid_id}",
                    "thumbnail": thumbnail_url,
                    "published_at": published[:10] if published else datetime.date.today().isoformat(),
                    "summary": summary or f"{ch['name']} 실시간 주요 뉴스 및 분석 영상입니다."
                })
        except Exception as e:
            print(f"    [!] 유튜브 채널({ch['name']}) 수집 건너뜀: {e}")

    # 최신순 및 다양성 정렬
    print(f"  └─ 유튜브 핫이슈 총 {len(results)}개 영상 큐레이션 완료")
    return results[:18]

if __name__ == "__main__":
    vids = collect_youtube_hot_issues()
    print("Collected videos:", len(vids))
