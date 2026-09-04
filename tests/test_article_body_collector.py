from pipeline.article_body_collector import _extract_jsonld_body, _extract_article_body, _event_overlap
from pipeline.fact_verifier import evaluate_article_fact_check
from bs4 import BeautifulSoup


def test_jsonld_article_body_extraction():
    body = "반도체 수출 증가로 경상수지 흑자 폭이 확대됐다. " * 12
    html = f'<script type="application/ld+json">{{"@type":"NewsArticle","articleBody":{body!r}}}</script>'
    # Python repr uses single quotes, so use a valid JSON payload instead.
    import json
    html = '<script type="application/ld+json">' + json.dumps({"@type":"NewsArticle","articleBody":body}, ensure_ascii=False) + '</script>'
    soup = BeautifulSoup(html, "html.parser")
    extracted = _extract_jsonld_body(soup)
    assert extracted and "경상수지" in extracted


def test_article_paragraph_extraction_ignores_short_noise():
    paras = ''.join(f'<p>원달러 환율 하락과 금융시장 움직임을 설명하는 충분히 긴 본문 문장입니다 {i}.</p>' for i in range(8))
    soup = BeautifulSoup('<article>'+paras+'</article>', 'html.parser')
    extracted = _extract_article_body(soup)
    assert extracted and len(extracted) >= 220


def test_body_event_overlap_requires_title_evidence():
    ok, ratio, shared = _event_overlap('원달러 환율 3거래일 연속 하락', '원달러 환율이 3거래일 연속 하락하면서 시장 변동성이 낮아졌다.')
    assert ok is True
    bad, _, _ = _event_overlap('원달러 환율 3거래일 연속 하락', '프로야구 경기에서 홈런이 나왔고 관중이 환호했다.')
    assert bad is False


def test_relay_domain_does_not_promote_multi_source():
    article = {
        'title':'테스트 기사', 'source':'경향신문', 'link':'https://www.khan.co.kr/article/1',
        'corroborating_urls':['https://v.daum.net/v/123456']
    }
    result = evaluate_article_fact_check(article)
    assert result['status'] == 'PARTIAL'
    assert 'v.daum.net' not in result['verified_sources']
    assert all('v.daum.net' not in u for u in result['evidence_urls'])


def test_real_second_domain_can_promote_multi_source():
    article = {
        'title':'테스트 기사', 'source':'경향신문', 'link':'https://www.khan.co.kr/article/1',
        'corroborating_urls':['https://www.hani.co.kr/arti/1','https://v.daum.net/v/123456']
    }
    result = evaluate_article_fact_check(article)
    assert result['status'] == 'VERIFIED_MULTI_SOURCE'
    assert result['verified_sources'] == ['khan.co.kr','hani.co.kr']
