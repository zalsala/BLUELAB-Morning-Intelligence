from __future__ import annotations

from pipeline.content_quality import chapter_relevance
from pipeline.fact_verifier import evaluate_article_fact_check


def _article(title: str, summary: str = "") -> dict:
    return {
        "title": title,
        "summary_raw": summary,
        "source": "테스트매체",
        "link": "https://example.com/story/1",
    }


def test_macro_rejects_game_dlc_title_even_if_summary_mentions_markets():
    art = _article(
        "집 짓고 바다 탐험한다…붉은사막 첫 DLC 10월 16일 출시",
        "증시와 시장에서 관련 기업 주가가 관심을 받았다. 금리와 환율 뉴스도 함께 노출됐다.",
    )
    result = chapter_relevance(art, "macro-finance")
    assert result["passed"] is False
    assert result["reason"] == "negative_title_signal"


def test_tech_rejects_realestate_financing_title():
    art = _article(
        "영끌대출 막히니 코인 1300억 팔았다…집 사려 가상자산도 손 댄 3040",
        "플랫폼과 IT 서비스 이용자 데이터가 함께 언급됐다.",
    )
    result = chapter_relevance(art, "tech-it")
    assert result["passed"] is False


def test_ai_accepts_gpt_release_title():
    art = _article("오픈AI, GPT-6 아스트라 출시…차세대 AI 모델 공개")
    result = chapter_relevance(art, "ai-deeptech")
    assert result["passed"] is True
    assert result["reason"] == "title_match"


def test_science_rejects_imported_car_sales_title():
    art = _article("테슬라, 8개월 만에 7.6만대 독주…수입차 연 10만대 눈앞")
    result = chapter_relevance(art, "science-future")
    assert result["passed"] is False


def test_single_media_domain_is_partial_not_multi_source():
    art = {
        "title": "단일 매체 기사",
        "summary_raw": "충분한 길이의 기사 요약",
        "source": "한국경제",
        "link": "https://www.hankyung.com/article/123",
        "editorial": {
            "fact": "매우 긴 사실 문장입니다. 기존 구현에서는 이것만으로 승격됐습니다.",
            "checkpoints": ["a", "b", "c"],
        },
    }
    result = evaluate_article_fact_check(art)
    assert result["status"] == "PARTIAL"
    assert result["evidence_type"] == "major_media"


def test_two_independent_domains_can_be_multi_source():
    art = {
        "title": "교차 검증 기사",
        "source": "테스트매체",
        "link": "https://example.com/story/1",
        "verification_evidence": [
            "https://example.net/corroboration/2",
            "https://example.com/duplicate-domain/3",
        ],
    }
    result = evaluate_article_fact_check(art)
    assert result["status"] == "VERIFIED_MULTI_SOURCE"
    assert set(result["verified_sources"]) == {"example.com", "example.net"}
    assert len(result["evidence_urls"]) == 2


def test_same_domain_corroboration_does_not_count_as_multi_source():
    art = {
        "title": "동일 도메인 반복",
        "source": "테스트매체",
        "link": "https://example.com/story/1",
        "verification_evidence": [
            "https://www.example.com/story/2",
            "https://example.com/story/3",
        ],
    }
    result = evaluate_article_fact_check(art)
    assert result["status"] == "PARTIAL"


def test_official_source_keeps_official_status_without_secondary_source():
    art = {
        "title": "한국은행 공식 발표",
        "source": "한국은행",
        "link": "https://www.bok.or.kr/portal/bbs/P0000559/view.do?nttId=1",
    }
    result = evaluate_article_fact_check(art)
    assert result["status"] == "VERIFIED_OFFICIAL"
