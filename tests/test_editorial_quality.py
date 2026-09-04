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


def _combined(editorial):
    return " ".join([editorial.fact, editorial.background, editorial.why_it_matters, *editorial.checkpoints])


def test_editorial_never_emits_ambiguous_korean_particle_placeholder():
    combined = _combined(build_editorial_for_article_v2(_article()))
    assert "을(를)" not in combined
    assert "이(가)" not in combined
    assert "은(는)" not in combined


def test_fact_rejects_google_news_or_daum_relay_fragment():
    editorial = build_editorial_for_article_v2(_article(
        summary_raw="연합뉴스 이 시각 헤드라인 - 10:30 v.daum.net [속보] 다른 사건 연합뉴스"
    ))
    assert "v.daum.net" not in editorial.fact
    assert "다른 사건" not in editorial.fact
    assert "세부 사실관계는 원문과 추가 근거에서 확인해야 합니다" in editorial.fact


def test_fact_uses_clean_article_summary_when_available():
    editorial = build_editorial_for_article_v2(_article())
    assert "반도체 수출 호조" in editorial.fact
    assert editorial.fact.startswith("한국경제 보도에 따르면")


def test_fact_rejects_unrelated_concatenated_headline_without_domain_marker():
    editorial = build_editorial_for_article_v2(_article(summary_raw=(
        "7월 경상수지 421억달러 흑자…반도체 호황에 역대 최대 한국경제 "
        "대한민국 정책브리핑 대한민국의 미래, 청년 과학기술인을 응원한다 "
        "안도걸 의원, 2027년도 예산안 관련 기자회견 뉴시스"
    )))
    assert "청년 과학기술인" not in editorial.fact
    assert "안도걸" not in editorial.fact
    assert "세부 사실관계는 원문과 추가 근거에서 확인해야 합니다" in editorial.fact


def test_fact_requires_same_event_overlap_not_just_long_fragment():
    editorial = build_editorial_for_article_v2(_article(
        summary_raw="정부가 로봇 200대를 구매하는 정책을 검토하면서 관련 기업 주가가 상승했다는 분석이 나왔다."
    ))
    assert "로봇 200대" not in editorial.fact
    assert "세부 사실관계는 원문과 추가 근거에서 확인해야 합니다" in editorial.fact


def test_fact_rejects_same_event_multi_publisher_cluster():
    editorial = build_editorial_for_article_v2(_article(
        title="월러 연준 이사 발언에 코스피 상승", source="MBC 뉴스",
        summary_raw="월러 연준 이사 발언에 코스피 상승 MBC 뉴스 월러 연준 이사 금리 인하 가능성 언급 뉴시스 코스피 장중 상승폭 확대 아시아경제",
    ))
    assert "뉴시스" not in editorial.fact
    assert "아시아경제" not in editorial.fact
    assert "세부 사실관계는 원문과 추가 근거에서 확인해야 합니다" in editorial.fact


def test_fact_rejects_neighboring_sub_event_with_partial_token_overlap():
    editorial = build_editorial_for_article_v2(_article(
        chapter_id="global-affairs", title='이란, 쿠웨이트 미군기지 공격…"이란 국민 상대 범죄 대응"',
        source="MBC 뉴스", summary_raw='불바다 된 이란 “보복작전 명칭은 번개…UAE·바레인 미군 기지 드론 공격”',
    ))
    assert "UAE" not in editorial.fact
    assert "바레인" not in editorial.fact


def test_aggregator_source_label_is_not_exposed_in_editorial_prose():
    editorial = build_editorial_for_article_v2(_article(source="v.daum.net", summary_raw=""))
    combined = _combined(editorial)
    assert "v.daum.net" not in combined
    assert "원문 매체" in combined


def test_known_domain_source_is_rendered_as_publisher_name_without_particle_error():
    editorial = build_editorial_for_article_v2(_article(
        source="yna.co.kr", title="7월 경상수지 420.8억달러 흑자…역대 두 번째 규모", summary_raw="",
    ))
    assert editorial.fact.startswith("연합뉴스 보도에 따르면")
    assert "연합뉴스는" not in editorial.fact
    assert "yna.co.kr" not in editorial.fact


def test_headline_echo_with_breaking_tag_and_source_falls_back():
    editorial = build_editorial_for_article_v2(_article(
        title="[속보] 7월 경상수지 421억달러 흑자…반도체 호황에 동월 역대 최대",
        summary_raw="[속보] 7월 경상수지 421억달러 흑자…반도체 호황에 동월 역대 최대 한국경제",
    ))
    assert "한국경제로 전해졌습니다" not in editorial.fact
    assert "세부 사실관계는 원문과 추가 근거에서 확인해야 합니다" in editorial.fact


def test_production_regression_khan_source_never_becomes_newspaper_neun():
    editorial = build_editorial_for_article_v2(_article(
        chapter_id="top-headlines",
        title="[속보]이 대통령 지지율 40%, 2%P↓···최저치 경신[한국갤럽]",
        source="경향신문",
        summary_raw="이 대통령 지지율 40%, 2%P↓···최저치 경신",
    ))
    assert "경향신문는" not in editorial.fact
    assert "경신로 전해졌습니다" not in editorial.fact
    assert editorial.fact.startswith("경향신문 보도에 따르면")


def test_production_regression_particle_tainted_keyword_is_normalized():
    editorial = build_editorial_for_article_v2(_article(
        title="미 국채 금리 진정에 기술주 반등… 코스피도 1%대 상승 출발",
        source="조선일보",
        summary_raw="",
    ))
    assert "진정에에" not in editorial.why_it_matters
    assert "진정에," not in editorial.why_it_matters
    assert "진정" in editorial.why_it_matters


def test_global_affairs_does_not_force_korean_export_template():
    editorial = build_editorial_for_article_v2(_article(
        chapter_id="global-affairs",
        title="이스라엘 안보 장관 가자 주민 이주 계획 언급",
        source="한겨레",
        summary_raw="",
    ))
    assert "수출 주도형 한국 경제" not in editorial.why_it_matters
    assert "해외 거점 생산 전략" not in editorial.why_it_matters
    assert "국제관계" in editorial.why_it_matters


def test_checkpoints_reflect_evidence_strength():
    multi = build_editorial_for_article_v2(_article())
    assert "a.example" in multi.checkpoints[1]
    assert "b.example" in multi.checkpoints[1]
    partial = build_editorial_for_article_v2(_article(fact_check={"evidence_urls": ["https://a.example/x"]}))
    assert "두 번째 근거" in partial.checkpoints[1]


def test_relay_domains_are_not_exposed_as_independent_checkpoint_evidence():
    editorial = build_editorial_for_article_v2(_article(fact_check={"evidence_urls": [
        "https://www.hankyung.com/article/1", "https://v.daum.net/v/123", "https://news.nate.com/view/456",
    ]}))
    assert "v.daum.net" not in editorial.checkpoints[1]
    assert "news.nate.com" not in editorial.checkpoints[1]
    assert "두 번째 근거" in editorial.checkpoints[1]


def test_background_and_why_are_article_specific():
    editorial = build_editorial_for_article_v2(_article())
    assert "7월 경상수지" in editorial.background
    assert "경상수지" in editorial.why_it_matters
