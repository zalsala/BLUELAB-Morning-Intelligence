from pipeline.article_body_collector import _extract_evidence_span
from pipeline.editorial_quality import build_editorial_for_article_v2, process_all_editorials


GROUNDED = "비트코인 8만1000달러 돌파와 금리 우려 완화가 시장에서 확인됐다."
TITLE = "비트코인 8만1000달러 돌파, 금리 우려 완화"


def _raw(status="VALIDATED", span=None):
    data = {
        "id": "a1",
        "chapter_id": "macro-finance",
        "chapter_name": "거시 경제 & 금융",
        "title": TITLE,
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
    span = _extract_evidence_span(TITLE, body)
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


def test_grounding_rejects_emoji_and_promotional_commentary():
    body = "😊 비트코인 8만1000달러 돌파는 투자자에게 좋은 기회가 될 거예요. " + GROUNDED
    assert _extract_evidence_span(TITLE, body) == GROUNDED


def test_grounding_rejects_headline_caption_echo():
    body = TITLE + " [사진=연합뉴스] 대표 이미지. " + GROUNDED
    assert _extract_evidence_span(TITLE, body) == GROUNDED


def test_grounding_never_accepts_mid_sentence_truncation():
    body = "비트코인 8만1000달러 돌파와 금리 우려 완화가 주요 시장 변수로 작용하며 추가 분석이 필요한 주요"
    assert _extract_evidence_span(TITLE, body) is None


def test_grounding_rejects_kbs_accessibility_boilerplate():
    title = "코스피, 1.6% 올라 6,680대 마감…코스닥도 닷새만 반등"
    bad = title + " 읽어주기 기능은 크롬기반의 브라우저에서만 사용하실 수 있습니다."
    good = "코스피는 전 거래일보다 1.6% 오른 6,680대에서 거래를 마쳤고 코스닥도 닷새 만에 반등했습니다."
    assert _extract_evidence_span(title, bad + " " + good) == good


def test_grounding_rejects_tagged_headline_plus_short_metadata_fragment():
    title = '[일문일답] "혹시 구글?"…KISO "해외 빅테크 2곳 이상, 회원가입 논의 중"'
    bad = title + " 한국인터넷자율정책기구(KISO) 회원사."
    good = "KISO는 해외 빅테크 기업 2곳 이상과 회원가입을 논의하고 있다고 밝혔습니다."
    assert _extract_evidence_span(title, bad + " " + good) == good


def test_grounding_rejects_vague_attention_commentary():
    title = "비바리퍼블리카, 토스 클라우드 상표 출원…내부 인프라 강화"
    bad = "비바리퍼블리카의 토스 클라우드 상표 출원 속에서 AWS 등 기존 인프라 환경이 주목받고 있습니다."
    good = "비바리퍼블리카는 토스 클라우드 상표를 출원했으며 내부 인프라 운영 강화를 검토하고 있습니다."
    assert _extract_evidence_span(title, bad + " " + good) == good
