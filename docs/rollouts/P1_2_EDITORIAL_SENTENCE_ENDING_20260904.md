# P1.2 Editorial Sentence Ending Rollout

- Scope: fail closed on headline-like RSS fragments that are not complete declarative sentences.
- Regression target: prevent malformed Korean constructions such as `경신로 전해졌습니다`.
- Branch validation: PASS (`33839368984`).
- Production promotion target: `72d9669185f7d46c425a50b78c7e063b091831af`.
- Policy: do not synthesize grammatical endings onto headline fragments; fall back to the selected headline and require the original article/evidence for detail.
