# BLUELAB Morning Intelligence

독립 Cloudflare Workers/Pages용 개인 뉴스 브리핑 프로젝트.

## 핵심 구조

- `public/index.html` — 고정 UI
- `public/assets/styles.css` — 반응형 디자인
- `public/assets/app.js` — JSON 렌더링/상세기사 모달
- `public/data/today.json` — 현재판 메타데이터
- `public/data/stories-1.json` ~ `stories-5.json` — 정확히 5개 활성 story bundle
- `public/data/archive/YYYY-MM-DD/` — 과거판 보관
- `config/source-policy.json` — 분야별 수집원·출처 다양성·정확한 기사 URL 정책
- `scripts/validate_sources.py` — 출처 편중·발견용 출처 오용·홈/섹션 URL 감사

## 수집 전략

Morning Intelligence는 한두 통신사에서 10개를 채우지 않는다. 각 챕터에서 먼저 30~50개의 후보를 넓게 발견한 뒤 다음 순서로 좁힌다.

1. 공식기관·규제기관·공시·논문·회사 newsroom 등 1차 자료
2. Reuters/AP/AFP 등 통신사와 주요 국제·국내 언론
3. 분야별 전문매체·산업매체
4. Google Trends, YouTube, Reddit/X/TikTok/Instagram, 집계·큐레이션 서비스는 발견용 신호로 사용
5. 최종 기사에는 정확히 해당 사건을 가리키는 article URL을 요구하고, 홈페이지·섹션 홈은 검증된 기사로 계산하지 않는다.

### 출처 다양성 목표

- 일반 챕터: 최소 5개 고유 도메인
- 전문·저빈도 챕터: 최소 4개 고유 도메인
- 단일 도메인 비중: 원칙적으로 40% 이하
- Reuters/AP/AFP 합산: 원칙적으로 50% 이하
- 1차자료 목표: 30% 이상
- 전문매체 목표: 20% 이상

정확한 허용·권장 도메인은 `config/source-policy.json`을 정본으로 사용한다.

## 검증

GitHub Actions는 기본 구조 외에도 `scripts/validate_sources.py`를 실행해 현재판의 실제 렌더 대상 기사 기준으로 출처 분포를 계산한다. 현행판은 기존 기사들을 새 정책으로 이관하는 동안 report mode로 감사를 수행하며, 다음 데이터 정비 단계에서 `--strict`를 활성화해 정책 위반을 CI 실패로 승격한다.

## Cloudflare 배포

- Framework preset: `None`
- Build output directory: `public`
- `main` 변경 시 자동 재배포

## 편집 정책

- 기사 전문을 그대로 복제/번역하지 않는다.
- 자연스러운 한국어 장문 재구성 + 팩트체크 + 정확한 원문 링크를 사용한다.
- 진행 중 사건은 CONFIRMED / PARTIALLY CONFIRMED / DISPUTED / UNVERIFIED를 구분한다.
- 과학·의료·시과학은 근거수준과 한계를 함께 기록한다.
- 주식·시장 해설은 투자 권유가 아니다.
