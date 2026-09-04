from types import SimpleNamespace

from pipeline.korean_quality import (
    polish_bundle_summary,
    polish_editorial_articles,
    polish_fact_text,
    polish_summary_line,
    polish_why_text,
    validate_korean_quality,
)
from pipeline.korean_text import has_final_consonant, object_particle


def test_object_particle_uses_hangul_jongseong():
    assert has_final_consonant("최대") is False
    assert has_final_consonant("혁신") is True
    assert object_particle("최대") == "를"
    assert object_particle("혁신") == "을"


def test_summary_regression_from_production_uses_reul_after_maximum():
    line = "[산업·경제 인텔리전스] '[속보] 7월 경상수지 421억달러 흑자…반도체 호황에 동월 역대 최대'을 비롯한 AI 경쟁"
    fixed = polish_summary_line(line)
    assert "역대 최대'를 비롯한" in fixed
    assert "역대 최대'을 비롯한" not in fixed


def test_summary_keeps_eul_when_headline_has_final_consonant():
    line = "[산업·경제 인텔리전스] 'AI 공급망 혁신'를 비롯한 반도체 경쟁"
    fixed = polish_summary_line(line)
    assert "AI 공급망 혁신'을 비롯한" in fixed


def test_why_regression_uses_particle_neutral_wording():
    text = "이 사안은 대통령, 시민사회, 초청와 직접 연결돼 있어 후속 판단에 영향을 줄 수 있습니다."
    fixed = polish_why_text(text)
    assert "초청에 직접 연결돼 있어" in fixed
    assert "초청와" not in fixed


def test_fact_quoted_headline_uses_ra_neun_reporting_form():
    text = "연합뉴스 보도에 따르면, ‘원/달러 환율 3거래일 연속 하락’이라는 내용이 전해졌습니다."
    fixed = polish_fact_text(text)
    assert "’라는 내용이 전해졌습니다" in fixed
    assert "’이라는 내용이 전해졌습니다" not in fixed


def test_bundle_quality_gate_passes_after_polish():
    editorial = SimpleNamespace(
        fact="원문 매체 보도에 따르면, ‘테스트 제목’이라는 내용이 전해졌습니다.",
        background="배경 설명입니다.",
        why_it_matters="이 사안은 대통령, 시민사회, 초청와 직접 연결돼 있어 후속 판단에 영향을 줄 수 있습니다.",
        checkpoints=["공식 발표 확인"],
    )
    article = SimpleNamespace(source="원문 매체", title="테스트 제목", editorial=editorial)
    bundle = SimpleNamespace(
        three_line_summary=[
            "[헤드라인] 첫째 줄",
            "[산업] '7월 경상수지 역대 최대'을 비롯한 시장 이슈",
            "[로컬] 셋째 줄",
        ],
        chapters=[SimpleNamespace(articles=[article])],
    )

    polish_editorial_articles([article])
    polish_bundle_summary(bundle)
    validate_korean_quality(bundle)

    assert "최대'를 비롯한" in bundle.three_line_summary[1]
    assert "초청에 직접" in article.editorial.why_it_matters
    assert "’라는 내용이 전해졌습니다" in article.editorial.fact


def test_quality_gate_rejects_ambiguous_placeholder():
    editorial = SimpleNamespace(
        fact="한국경제을(를) 확인했습니다.", background="배경", why_it_matters="중요성", checkpoints=[],
    )
    bundle = SimpleNamespace(three_line_summary=["a", "b", "c"], chapters=[SimpleNamespace(articles=[SimpleNamespace(editorial=editorial)])])
    try:
        validate_korean_quality(bundle)
    except ValueError as exc:
        assert "ambiguous particle placeholder" in str(exc)
    else:
        raise AssertionError("quality gate must fail closed")


def test_quality_gate_rejects_unpolished_quoted_reporting_particle():
    editorial = SimpleNamespace(
        fact="연합뉴스 보도에 따르면, ‘테스트’이라는 내용이 전해졌습니다.", background="배경", why_it_matters="중요성", checkpoints=[],
    )
    bundle = SimpleNamespace(three_line_summary=["a", "b", "c"], chapters=[SimpleNamespace(articles=[SimpleNamespace(editorial=editorial)])])
    try:
        validate_korean_quality(bundle)
    except ValueError as exc:
        assert "quoted-headline reporting" in str(exc)
    else:
        raise AssertionError("quality gate must fail closed")


def test_production_regression_ellipsis_fact_fails_closed_to_full_headline():
    title = "비트코인, 美 금리 인상 우려 완화에 급등... 3개월 만에 8만1000달러 돌파"
    editorial = SimpleNamespace(
        fact="조선일보 보도에 따르면, 비트코인, 美 금리 인상 우려 완화에 급등...",
        background="배경 설명입니다.", why_it_matters="중요성 설명입니다.", checkpoints=["후속 확인"],
    )
    article = SimpleNamespace(source="조선일보", title=title, editorial=editorial)
    polish_editorial_articles([article])
    assert editorial.fact == (
        "조선일보 보도에 따르면, ‘비트코인, 美 금리 인상 우려 완화에 급등... 3개월 만에 8만1000달러 돌파’"
        "라는 내용이 전해졌습니다. 세부 사실관계는 원문과 추가 근거에서 확인해야 합니다."
    )
    assert not editorial.fact.endswith("급등...")


def test_quality_gate_rejects_unpolished_ellipsis_fact_fragment():
    editorial = SimpleNamespace(
        fact="조선일보 보도에 따르면, 비트코인, 美 금리 인상 우려 완화에 급등...",
        background="배경", why_it_matters="중요성", checkpoints=[],
    )
    article = SimpleNamespace(source="조선일보", title="비트코인 전체 제목", editorial=editorial)
    bundle = SimpleNamespace(three_line_summary=["a", "b", "c"], chapters=[SimpleNamespace(articles=[article])])
    try:
        validate_korean_quality(bundle)
    except ValueError as exc:
        assert "incomplete fact clause ending in ellipsis" in str(exc)
    else:
        raise AssertionError("quality gate must reject incomplete ellipsis Fact")


def test_valid_grounded_fact_is_unchanged():
    fact = "연합뉴스 원문에 따르면, 코스피는 1.6% 상승해 거래를 마쳤습니다."
    editorial = SimpleNamespace(fact=fact, background="배경", why_it_matters="중요성", checkpoints=[])
    article = SimpleNamespace(source="연합뉴스", title="코스피 상승 마감", editorial=editorial)
    polish_editorial_articles([article])
    assert editorial.fact == fact
