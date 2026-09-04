from pipeline.editorial_quality import build_editorial_for_article_v2


def _article(**overrides):
    base = {
        "chapter_id": "macro-finance",
        "title": "7월 경상수지 421억달러 흑자…반도체 호황에 역대 최대",
        "source": "한국경제",
        "summary_raw": "7월 경상수지 흑자가 반도체 수출 호조에 힘입어 동월 기준 역대 최대를 기록했다.",
        "fact_check": {"evidence_urls": ["https://a.example/x", "https://b.example/y"]},
    }
    base.update(overrides)
    return base


def test_editorial_never_emits_ambiguous_korean_particle_placeholder():
    editorial = build_editorial_for_article_v2(_article())
    combined = " ".join([editorial.fact, editorial.background, editorial.why_it_matters, *editorial.checkpoints])
    assert "을(를)" not in combined
    assert "이(가)" not in combined


def test_fact_rejects_google_news_or_daum_relay_fragment():
    editorial = build_editorial_for_article_v2(_article(
        summary_raw="연합뉴스 이 시각 헤드라인 - 10:30 v.daum.net [속보] 다른 사건 연합뉴스"
    ))
    assert "v.daum.net" not in editorial.fact
    assert "다른 사건" not in editorial.fact
    assert "세부 수치는 원문과 추가 근거에서 확인해야 합니다" in editorial.fact


def test_fact_uses_clean_article_summary_when_available():
    editorial = build_editorial_for_article_v2(_article())
    assert "반도체 수출 호조" in editorial.fact
    assert editorial.fact.startswith("한국경제 보도에 따르면")


def test_checkpoints_reflect_evidence_strength():
    multi = build_editorial_for_article_v2(_article())
    assert "a.example" in multi.checkpoints[1]
    assert "b.example" in multi.checkpoints[1]

    partial = build_editorial_for_article_v2(_article(fact_check={"evidence_urls": ["https://a.example/x"]}))
    assert "두 번째 근거" in partial.checkpoints[1]


def test_background_and_why_are_article_specific():
    editorial = build_editorial_for_article_v2(_article())
    assert "7월 경상수지" in editorial.background
    assert "경상수지" in editorial.why_it_matters
