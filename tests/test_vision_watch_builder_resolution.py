import json
from collections import Counter

from pipeline import vision_watch_builder as vwb


def test_crossref_primary_resource_fallback(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "message": {
                        "resource": {
                            "primary": {
                                "URL": "https://publisher.example/article/123"
                            }
                        }
                    }
                }
            ).encode("utf-8")

    monkeypatch.setattr(vwb.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    assert vwb._crossref_resource_url("10.1000/example") == "https://publisher.example/article/123"


def test_build_expands_ranked_reserve_before_failing_domain_diversity(monkeypatch):
    topics = ["myopia", "binocular", "contact_cornea", "ophthalmology", "vision_science", "optometry"]
    domains = ["a.example", "b.example", "c.example", "d.example"]
    candidates = []
    for i in range(47):
        domain = "e.example" if i == 46 else domains[i % len(domains)]
        candidates.append(
            {
                "doi": f"10.1000/{i}",
                "title": f"Vision research {i}",
                "topic_id": topics[i % len(topics)],
                "topic_label": topics[i % len(topics)],
                "publication_date": "2026-09-05",
                "selection_score": 100 - i,
                "url": f"https://{domain}/article/{i}",
                "exact_source_url": f"https://{domain}/article/{i}",
                "collector_source": "crossref",
                "evidence_type": "RESEARCH / ISSUE",
            }
        )

    monkeypatch.setattr(vwb, "_collect", lambda days, limit_per_source=12: (candidates, []))

    def fake_select(items, target, max_share, today):
        chosen = items[: min(target, len(items))]
        return chosen, Counter(x["topic_id"] for x in chosen), Counter(x["collector_source"] for x in chosen), Counter(), len(items)

    monkeypatch.setattr(vwb, "select", fake_select)
    monkeypatch.setattr(vwb, "_resolve_reserve", lambda items: [dict(x) for x in items])

    chapter, report = vwb.build_vision_watch(target=10)
    assert chapter["count"] == 10
    assert report["coverage_status"] == "PASS"
    assert len(report["exact_source_domains"]) >= 5
    assert report["reserve_count"] == 47
