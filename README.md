# BLUELAB Morning Intelligence

독립 Cloudflare Pages용 뉴스 브리핑 프로젝트.

## 핵심 구조

- `public/index.html` — 고정 UI
- `public/assets/styles.css` — 밝은 저자극 반응형 디자인
- `public/assets/app.js` — JSON 렌더링/상세기사 모달
- `public/data/today.json` — 매일 교체되는 뉴스 데이터
- `public/data/archive/YYYY-MM-DD.json` — 과거판 보관
- `public/prototype-v9.html` — 현재까지 만든 V9 원형 참고본

즉, 매일 전체 HTML을 다시 만들 필요 없이 `today.json`과 날짜별 아카이브 JSON을 갱신하면 됩니다.

## Cloudflare Pages 배포

1. GitHub에 새 저장소 `BLUELAB-Morning-Intelligence` 생성
2. 이 프로젝트의 파일을 저장소 루트에 업로드
3. Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git
4. 새 GitHub 저장소 선택
5. Framework preset: `None`
6. Build command: 비워 둠
7. Build output directory: `public`
8. Deploy

이후 `main` 브랜치가 바뀌면 Cloudflare가 자동 재배포합니다.

## 다음 자동화 단계

매일 아침 수집/검증 파이프라인이 아래 파일만 갱신하도록 구성합니다.

- `public/data/today.json`
- `public/data/archive/<DATE>.json`

뉴스 소스: Google Trends, Reuters/AP/공식기관, 기업 공시/발표, 시장 데이터, YouTube/Shorts, PubMed/저널, 안경·안과 산업 공식 소스.

## 정책

- 기사 전문을 그대로 복제/번역하지 않음
- 한국어 장문 재구성 + 팩트체크 + 원문 링크
- 진행 중 사건은 확인/부분확인/미확인 구분
- 주식 Watchlist는 투자 권유가 아님
