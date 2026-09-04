from datetime import datetime, timezone

from pipeline.schema import Article, EditorialContent
from pipeline.top5_ranker import score_top5_candidate, select_top5_v2


def _article(id_, chapter, score=10.0, status="PARTIAL", body="NO_QUALIFIED_BODY", published="Fri, 04 Sep 2026 09:00:00 GMT"):
    return Article(
        id=id_, chapter_id=chapter, chapter_name=chapter, title=f"기사 {id_}",
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
