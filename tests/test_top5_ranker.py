from datetime import datetime, timezone

from pipeline.schema import Article, EditorialContent
from pipeline.top5_ranker import is_top5_eligible, score_top5_candidate, select_top5_v2


def _article(id_, chapter, score=10.0, status="PARTIAL", body="NO_QUALIFIED_BODY", published="Fri, 04 Sep 2026 09:00:00 GMT", title=None):
    return Article(
        id=id_, chapter_id=chapter, chapter_name=chapter, title=title or f"기사 {id_}",
        link=f"https://example.com/{id_}", source="테스트", published_at=published,
        summary_raw="", editorial=EditorialContent("f","b","w",["c"]),
        importance_score=score,
        fact_check={"status":status,"body_validation":{"status":body}},
    )


def test_verified_and_body_validated_article_beats_partial_at_same_base_score():
    now=datetime(2026,9,4,10,0,0,tzinfo=timezone.utc)
    strong=_article("strong","macro-finance",10,"VERIFIED_MULTI_SOURCE","VALIDATED")
    weak=_article("weak","macro-finance",10,"PARTIAL","EVENT_MISMATCH")
    assert score_top5_candidate(strong,now)[0] > score_top5_candidate(weak,now)[0]


def test_global_and_macro_impact_receive_more_weight_than_culture_at_same_evidence():
    now=datetime(2026,9,4,10,0,0,tzinfo=timezone.utc)
    macro=_article("macro","macro-finance",10,"VERIFIED_MULTI_SOURCE","VALIDATED")
    culture=_article("culture","culture-entertainment",10,"VERIFIED_MULTI_SOURCE","VALIDATED")
    assert score_top5_candidate(macro,now)[0] > score_top5_candidate(culture,now)[0]


def test_top5_first_pass_has_chapter_diversity():
    arts=[
        _article("m1","macro-finance",15,"VERIFIED_MULTI_SOURCE","VALIDATED"),
        _article("m2","macro-finance",14.9,"VERIFIED_MULTI_SOURCE","VALIDATED"),
        _article("g1","global-affairs",13,"VERIFIED_MULTI_SOURCE","VALIDATED"),
        _article("p1","politics-policy",12,"VERIFIED_OFFICIAL","VALIDATED"),
        _article("a1","ai-deeptech",11,"VERIFIED_PRIMARY","VALIDATED"),
        _article("s1","society-environment",10,"VERIFIED_MULTI_SOURCE","VALIDATED"),
    ]
    selected=select_top5_v2(arts,datetime(2026,9,4,10,0,0,tzinfo=timezone.utc))
    assert len(selected)==5
    assert len({a.chapter_id for a in selected})==5
    assert "m1" in {a.id for a in selected}
    assert "m2" not in {a.id for a in selected}


def test_partial_article_can_remain_eligible_but_is_penalized():
    now=datetime(2026,9,4,10,0,0,tzinfo=timezone.utc)
    high_partial=_article("partial","macro-finance",20,"PARTIAL","NO_QUALIFIED_BODY")
    lower_verified=_article("verified","global-affairs",10,"VERIFIED_MULTI_SOURCE","VALIDATED")
    assert score_top5_candidate(high_partial,now)[0] > score_top5_candidate(lower_verified,now)[0]


def test_explicit_editorial_and_column_labels_are_not_top5_eligible():
    labels = ["[사설] 정책 평가", "[칼럼] 시장 전망", "기고: 규제 제언", "오피니언: 오늘의 시각"]
    for idx, title in enumerate(labels):
        assert not is_top5_eligible(_article(f"op{idx}", "top-headlines", 20, "VERIFIED_MULTI_SOURCE", "VALIDATED", title=title))


def test_opinion_article_cannot_displace_factual_news_in_top5():
    arts = [
        _article("editorial", "top-headlines", 30, "VERIFIED_MULTI_SOURCE", "VALIDATED", title="[사설] 대통령 인사 비판"),
        _article("news1", "top-headlines", 14, "VERIFIED_MULTI_SOURCE", "VALIDATED", title="정부, 새 정책 일정 발표"),
        _article("news2", "macro-finance", 13, "VERIFIED_MULTI_SOURCE", "VALIDATED"),
        _article("news3", "global-affairs", 12, "VERIFIED_MULTI_SOURCE", "VALIDATED"),
        _article("news4", "politics-policy", 11, "VERIFIED_MULTI_SOURCE", "VALIDATED"),
        _article("news5", "ai-deeptech", 10, "VERIFIED_PRIMARY", "VALIDATED"),
    ]
    selected=select_top5_v2(arts,datetime(2026,9,4,10,0,0,tzinfo=timezone.utc))
    ids={a.id for a in selected}
    assert "editorial" not in ids
    assert ids == {"news1","news2","news3","news4","news5"}
