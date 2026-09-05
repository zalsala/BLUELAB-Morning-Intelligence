from copy import deepcopy

from scripts.validate_pre_send import EXPECTED_STORY_FILES, validate_bundle


def article(i, chapter, domain="news.example"):
    return {"title": f"Article {chapter}-{i}", "link": f"https://{domain}/{chapter}/{i}"}


def vision_article(i, domain):
    return {
        "title": f"Vision {i}",
        "link": f"https://{domain}/vision/{i}",
        "research_watch": {
            "evidence_type": "RCT",
            "study_design": "RCT",
            "clinical_meaning_ko": "임상적 의미",
            "limitations_conflicts_ko": "한계 확인",
            "exact_source_url": f"https://{domain}/vision/{i}",
        },
    }


def valid_bundle():
    general = []
    for c in range(14):
        general.append({
            "id": f"chapter-{c}",
            "name": f"Chapter {c}",
            "articles": [article(i, c, f"news{c}.example") for i in range(10)],
        })
    vision_domains = ["a.example", "b.example", "c.example", "d.example", "e.example"]
    vision = {
        "id": "vision-research-watch",
        "name": "Vision Research Watch",
        "articles": [vision_article(i, vision_domains[i % 5]) for i in range(10)],
    }
    top5 = [dict(general[i]["articles"][0]) for i in range(5)]
    videos = [{"channel": f"Channel {i % 5}"} for i in range(10)]
    return {
        "metadata": {"date": "2026-09-05", "story_files": EXPECTED_STORY_FILES},
        "chapters": general + [vision],
        "top_5_highlights": top5,
        "youtube_hot_issues": videos,
        "trending_keywords": [],
        "three_line_summary": ["one", "two", "three"],
        "weather": {"source": "official", "source_level": "primary"},
    }


def test_canonical_14_general_plus_one_vision_passes():
    assert validate_bundle(valid_bundle(), "2026-09-05") == []


def test_missing_vision_fails_closed():
    data = valid_bundle()
    data["chapters"] = data["chapters"][:-1]
    errors = validate_bundle(data, "2026-09-05")
    assert any("vision research chapter count=0" in e for e in errors)
    assert any("total rendered chapter count=14" in e for e in errors)


def test_second_vision_chapter_is_rejected():
    data = valid_bundle()
    duplicate = deepcopy(data["chapters"][-1])
    for i, item in enumerate(duplicate["articles"]):
        item["link"] = f"https://duplicate.example/{i}"
        item["research_watch"]["exact_source_url"] = item["link"]
    data["chapters"].append(duplicate)
    errors = validate_bundle(data, "2026-09-05")
    assert any("vision research chapter count=2" in e for e in errors)
    assert any("total rendered chapter count=16" in e for e in errors)


def test_vision_requires_five_source_domains():
    data = valid_bundle()
    for i, item in enumerate(data["chapters"][-1]["articles"]):
        domain = f"d{i % 4}.example"
        item["link"] = f"https://{domain}/vision/{i}"
        item["research_watch"]["exact_source_url"] = item["link"]
    errors = validate_bundle(data, "2026-09-05")
    assert any("VISION RESEARCH WATCH source domains=4 < 5" in e for e in errors)


def test_trends_must_be_zero_or_exactly_twenty():
    data = valid_bundle()
    data["trending_keywords"] = [str(i) for i in range(10)]
    errors = validate_bundle(data, "2026-09-05")
    assert any("trending keyword count must be 0 or 20" in e for e in errors)
