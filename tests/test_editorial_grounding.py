from pipeline.article_body_collector import _extract_evidence_span
from pipeline.editorial_quality import build_editorial_for_article_v2, process_all_editorials


GROUNDED = "비트코인 8만1000달러 돌파와 금리 우려 완화가 시장에서 확인됐다."


def _raw(status="VALIDATED", span=None):
    data = {
        "id": "a1",
        "chapter_id": "macro-finance",
        "chapter_name": "거시 경제 & 금융",
        "title": "비트코인 8만1000달러 돌파, 금리 우려 완화",
        "link": "https://example.com/a1",
        "source": "연합뉴스",
        "published_at": "Fri, 04 Sep 2026 00:00:00 GMT",
        "summary_raw": "비트코인 관련 보도 연합뉴스 다른 기사 제목 v.daum.net",
        "importance_score": 10.0,
        "fact_check": {"status": "VERIFIED_MULTI_SOURCE", "body_validation": {"status": status}, "evidence_urls": ["https://example.com/a1", "https://other.example/a1"]},
        "image": {"status": "EXPLICIT_NULL", "url": None},
    }
    if span:
        data["_body_evidence_span"] = span
    return data


def test_extract_evidence_span_prefers_title_grounded_sentence():
    body = "서울 날씨는 맑고 시민들이 공원을 찾았다. " + GROUNDED + " 시장에서는 향후 정책 방향을 주시하고 있다."
    span = _extract_evidence_span("비트코인 8만1000달러 돌파, 금리 우려 완화", body)
    assert span is not None
    assert "비트코인" in span and "8만1000달러" in span
    assert len(span) <= 240


def test_validated_body_span_is_used_before_summary_fallback():
    editorial = build_editorial_for_article_v2(_raw(span=GROUNDED))
    assert editorial.fact.startswith("연합뉴스 원문에 따르면")
    assert "8만1000달러" in editorial.fact
    assert "v.daum.net" not in editorial.fact


def test_nonvalidated_body_span_is_never_used():
    editorial = build_editorial_for_article_v2(_raw(status="EVENT_MISMATCH", span=GROUNDED))
    assert not editorial.fact.startswith("연합뉴스 원문에 따르면")


def test_unrelated_or_incomplete_span_fails_closed():
    editorial = build_editorial_for_article_v2(_raw(span="프로야구 경기에서 홈런이 나왔다."))
    assert not editorial.fact.startswith("연합뉴스 원문에 따르면")


def test_private_evidence_span_is_not_persisted_in_article_output():
    article = process_all_editorials([_raw(span=GROUNDED)])[0]
    exported = article.to_dict()
    assert "_body_evidence_span" not in exported
    assert "_body_evidence_span" not in str(exported)
