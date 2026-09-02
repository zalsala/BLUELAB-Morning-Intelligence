# Morning Intelligence QA Architecture

## State model

`DETERMINISTIC_CI_PASS` does not imply `RELEASE_PASS`, and `RELEASE_PASS` does not imply `LIVE_PASS`.

1. **Deterministic CI**: network-free structure, schema, regression and corpus checks.
2. **Release Gate**: current public data contract, live acquisition, editorial selection and strict source audit.
3. **Deploy Gate**: deployment of the accepted commit.
4. **Live Gate**: read-back of the deployed commit/data plus desktop/mobile interaction checks.

Only all four gates together may produce `COMPLETE_AND_LIVE`.

## Fail-closed rules

- Exactly five active story bundles.
- TOP5 is exactly five unique bundle titles.
- Every configured chapter renders at least 10 items **after TOP5 exclusion**.
- Release mode requires exactly 20 Trends rows, weather essentials, market metrics, and at least 10 video records.
- Release mode runs `validate_sources.py --strict`.
- Live acquisition failures may be allowed to finish for evidence collection, but the final release-decision step MUST fail if any required step outcome is not `success`.
- Candidate quota never overrides editorial quality. A chapter below 10 valid items remains incomplete.
- Production data is not mutated by candidate collectors or selectors.

## Editorial evaluation

`evals/editorial-gold.jsonl` is the canonical regression seed. Add every discovered false positive, false negative and event-duplicate example. The evaluator reports classification precision/recall and event-dedup correctness.

The seed corpus is intentionally small. `PRECISION_AT_10_READINESS=SEED_CORPUS_INCOMPLETE` is expected until each priority chapter has at least 10 adjudicated candidates. Do not fabricate labels merely to make the metric ready.

Target once ready:
- precision@10 >= 0.90 per priority chapter
- no known regression mismatch
- event duplicate regression = 100%

## Next hardening

- Replace selector `asof=max(candidate published)` with explicit run timestamp.
- Add canonical URL/title/date verification before editorial selection.
- Add global cross-chapter arbitration.
- Add source health/retry/backoff telemetry.
- Expand the gold corpus from real run artifacts before enforcing precision thresholds.
