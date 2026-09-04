import copy
import json

from scripts.qa_gate import run_qa_gate


CHAPTER_IDS = [
    "top-headlines", "politics-policy", "macro-finance", "global-affairs", "tech-it",
    "ai-deeptech", "semiconductors-mfg", "bio-healthcare", "energy-mobility",
    "realestate-construction", "retail-consumer", "society-environment",
    "culture-entertainment", "science-future",
]


def _article(chapter_id, index):
    article_id = f"{chapter_id}-{index}"
    return {
        "id": article_id,
        "chapter_id": chapter_id,
        "chapter_name": chapter_id,
        "title": f"사실 보도 {article_id}",
        "link": f"https://example.com/{article_id}",
        "editorial": {
            "fact": "검증 가능한 사실 보도입니다.",
            "background": "충분한 배경 설명이 포함되어 있습니다.",
            "why_it_matters": "후속 영향을 확인할 필요가 있습니다.",
            "checkpoints": ["원문 업데이트", "후속 공식 발표"],
        },
        "fact_check": {
            "status": "PARTIAL",
            "body_validation": {"status": "NO_QUALIFIED_BODY"},
        },
        "image": {
            "url": None,
            "source_domain": None,
            "status": "EXPLICIT_NULL",
            "reason": "NO_CANDIDATE",
        },
    }


def _valid_bundle():
    chapters = []
    for chapter_id in CHAPTER_IDS:
        articles = [_article(chapter_id, i) for i in range(10)]
        chapters.append({"id": chapter_id, "name": chapter_id, "articles": articles})

    top5 = [copy.deepcopy(chapters[i]["articles"][0]) for i in range(5)]
    return {
        "metadata": {"version": "1.1.0", "trends_source": "WITHHELD_INSUFFICIENT_RELIABLE_TERMS"},
        "chapters": chapters,
        "top_5_highlights": top5,
        "weather": {"location": "인천 서구 검단", "temp_current": 22.0},
        "market": {"kospi": {}, "usd_krw": {}},
        "next_signals": [{}, {}, {}],
        "trending_keywords": [],
        "three_line_summary": ["1", "2", "3"],
        "youtube_hot_issues": [{"channel": f"channel-{i % 4}"} for i in range(10)],
        "integrity_hash": "a" * 64,
    }


def _write(tmp_path, data):
    path = tmp_path / "today.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_valid_bundle_passes_hardened_gate(tmp_path):
    assert run_qa_gate(_write(tmp_path, _valid_bundle()))


def test_top5_opinion_is_rejected_even_if_count_is_five(tmp_path):
    data = _valid_bundle()
    data["top_5_highlights"][0]["title"] = "[사설] 사실 뉴스처럼 보이는 의견"
    assert not run_qa_gate(_write(tmp_path, data))


def test_top5_outside_canonical_snapshot_is_rejected(tmp_path):
    data = _valid_bundle()
    data["top_5_highlights"][0]["id"] = "outsider"
    data["top_5_highlights"][0]["link"] = "https://example.com/outsider"
    assert not run_qa_gate(_write(tmp_path, data))


def test_missing_body_validation_is_rejected(tmp_path):
    data = _valid_bundle()
    del data["chapters"][0]["articles"][0]["fact_check"]["body_validation"]
    assert not run_qa_gate(_write(tmp_path, data))


def test_verified_image_without_provenance_fields_is_rejected(tmp_path):
    data = _valid_bundle()
    data["chapters"][0]["articles"][0]["image"] = {
        "url": "https://img.example.com/a.jpg",
        "status": "VERIFIED_PROVENANCE",
        "content_hash": "hash-a",
    }
    assert not run_qa_gate(_write(tmp_path, data))


def test_duplicate_verified_image_hash_is_rejected(tmp_path):
    data = _valid_bundle()
    for idx in (0, 1):
        data["chapters"][0]["articles"][idx]["image"] = {
            "url": f"https://img.example.com/{idx}.jpg",
            "status": "VERIFIED_PROVENANCE",
            "content_hash": "same-content-hash",
            "declaration_method": "og:image",
            "source_domain": "img.example.com",
            "article_domain": "example.com",
        }
    assert not run_qa_gate(_write(tmp_path, data))


def test_top5_requires_five_distinct_chapters(tmp_path):
    data = _valid_bundle()
    data["top_5_highlights"][4] = copy.deepcopy(data["chapters"][0]["articles"][1])
    assert not run_qa_gate(_write(tmp_path, data))
