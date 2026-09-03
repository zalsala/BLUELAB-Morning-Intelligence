"""
pipeline/schema.py
BLUELAB Morning Intelligence 데이터 규격 및 14개 챕터 메타데이터 정의
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

# 14개 챕터 메타데이터 정의
CHAPTER_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "top-headlines",
        "name": "주요 헤드라인",
        "name_en": "Top Headlines",
        "icon": "⚡",
        "description": "오늘 아침 가장 주목해야 할 국가적·글로벌 종합 주요 뉴스",
        "queries": ["속보", "헤드라인", "종합", "주요 뉴스", "국내외 주요 이슈"],
        "rss_topics": ["CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB"], # Google News Top Stories
    },
    {
        "id": "politics-policy",
        "name": "정치 & 정책",
        "name_en": "Politics & Policy",
        "icon": "🏛️",
        "description": "국회, 대통령실, 행정부 정책 입안 및 주요 법안 입법 동향",
        "queries": ["대통령실 정책", "국회 법안", "정부 발표", "여야 합의", "행정 규제"],
        "rss_topics": [],
    },
    {
        "id": "macro-finance",
        "name": "거시 경제 & 금융",
        "name_en": "Macro Economy & Finance",
        "icon": "📈",
        "description": "한국은행 금리, 환율, 증시 지수, 채권, 거시경제 지표 및 금융 시장",
        "queries": ["기준금리", "코스피 코스닥", "원달러 환율", "물가 지수", "금융위원회"],
        "rss_topics": ["CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB"], # Business
    },
    {
        "id": "global-affairs",
        "name": "글로벌 국제 정세",
        "name_en": "Global Affairs",
        "icon": "🌐",
        "description": "미국 대선/연준, 미중 갈등, 지정학적 안보 및 글로벌 무역 통상",
        "queries": ["미국 연준 FOMC", "미중 갈등", "글로벌 공급망", "유럽연합 통상", "국제 안보"],
        "rss_topics": ["CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtdHZHZ0pMVWlnQVAB"], # World
    },
    {
        "id": "tech-it",
        "name": "테크 & IT 산업",
        "name_en": "Tech & IT",
        "icon": "💻",
        "description": "빅테크 플랫폼, 클라우드, 사이버 보안, 스마트폰 및 SW 산업",
        "queries": ["빅테크", "클라우드 서비스", "사이버 보안", "IT 플랫폼", "소프트웨어 기업"],
        "rss_topics": ["CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB"], # Technology
    },
    {
        "id": "ai-deeptech",
        "name": "인공지능 & 딥테크",
        "name_en": "AI & DeepTech",
        "icon": "🤖",
        "description": "생성형 AI, LLM 파운데이션 모델, 자율 에이전트, 로보틱스, 양자 기술",
        "queries": ["인공지능 생성형", "LLM 모델", "AI 로봇", "딥테크 스타트업", "양자 컴퓨팅"],
        "rss_topics": [],
    },
    {
        "id": "semiconductors-mfg",
        "name": "반도체 & 첨단제조",
        "name_en": "Semiconductors & Manufacturing",
        "icon": "🔬",
        "description": "HBM, 메모리/비메모리 반도체, 파운드리, 이차전지 배터리, 첨단 소재",
        "queries": ["삼성전자 SK하이닉스 반도체", "HBM 패키징", "파운드리 공정", "이차전지 배터리", "디스플레이 첨단소재"],
        "rss_topics": [],
    },
    {
        "id": "bio-healthcare",
        "name": "바이오 & 헬스케어",
        "name_en": "Bio & Healthcare",
        "icon": "🧬",
        "description": "신약 개발, 바이오시밀러, FDA 임상, 디지털 헬스케어, 의료 AI",
        "queries": ["바이오 신약", "임상 3상", "FDA 승인", "의료 AI 솔루션", "제약 바이오"],
        "rss_topics": [],
    },
    {
        "id": "energy-mobility",
        "name": "에너지 & 모빌리티",
        "name_en": "Energy & Mobility",
        "icon": "⚡",
        "description": "전기차, 수소차, 자율주행, 원자력, 태양광/풍력 신재생에너지 및 전력망",
        "queries": ["전기차 자율주행", "원자력 발전 SMR", "신재생에너지 태양광", "전력망 그리드", "모빌리티 UAM"],
        "rss_topics": [],
    },
    {
        "id": "realestate-construction",
        "name": "부동산 & 건설",
        "name_en": "Real Estate & Construction",
        "icon": "🏢",
        "description": "수도권 아파트 분양/매매, 전월세, 재건축, 부동산 PF, 국토교통 인프라",
        "queries": ["부동산 아파트 청약", "재건축 재개발", "부동산 PF", "국토교통부 분양", "수도권 집값"],
        "rss_topics": [],
    },
    {
        "id": "retail-consumer",
        "name": "유통 & 소비재",
        "name_en": "Retail & Consumer",
        "icon": "🛍️",
        "description": "이커머스 커머스 플랫폼, 대형마트/백화점, K-푸드, 뷰티, 물가 및 소비 패턴",
        "queries": ["이커머스 쿠팡 알리", "유통 백화점", "K푸드 수출", "소비자 물가", "패션 뷰티 트렌드"],
        "rss_topics": [],
    },
    {
        "id": "society-environment",
        "name": "사회 & 노동/환경",
        "name_en": "Society & Environment",
        "icon": "👥",
        "description": "고용·노동 환경, ESG 경영, 탄소중립, 저출산·고령화, 사법 및 사회적 이슈",
        "queries": ["고용 노동 시장", "ESG 탄소중립", "저출산 고령화 대책", "환경 규제", "사회 안전망"],
        "rss_topics": [],
    },
    {
        "id": "culture-entertainment",
        "name": "문화 & 미디어/엔터",
        "name_en": "Culture & Media",
        "icon": "🎬",
        "description": "K-POP, 드라마/영화, OTT 스트리밍, 게임, 웹툰, 글로벌 문화 콘텐츠",
        "queries": ["K-POP 음원", "OTT 드라마 영화", "게임 신작", "웹툰 콘텐츠", "엔터테인먼트 기획사"],
        "rss_topics": ["CAAqJggKIiBDQkFTRWdvSUwyMHZNRGpxTXpNU0FtdHZHZ0pMVWlnQVAB"], # Entertainment
    },
    {
        "id": "science-future",
        "name": "과학 & 미래기술",
        "name_en": "Science & Future Tech",
        "icon": "🚀",
        "description": "우주항공(누리호/달탐사), 핵융합, 양자센서, 차세대 소재, 기초과학 혁신",
        "queries": ["우주항공청 로켓", "핵융합 인공태양", "차세대 신소재", "기초과학 연구", "미래 혁신기술"],
        "rss_topics": ["CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtdHZHZ0pMVWlnQVAB"], # Science
    },
]

# 챕터 ID 매핑 딕셔너리
CHAPTER_MAP: Dict[str, Dict[str, Any]] = {c["id"]: c for c in CHAPTER_DEFINITIONS}


@dataclass
class EditorialContent:
    """기사별 정밀 4대 에디토리얼 분석 데이터"""
    fact: str                    # 핵심 팩트 (육하원칙 요약)
    background: str              # 사건 배경 (산업/정책 맥락)
    why_it_matters: str          # 왜 중요한가 (시장·의사결정 파급효과)
    checkpoints: List[str]       # 향후 체크포인트 (2~3개 관전 포인트)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Article:
    """개별 뉴스 기사 데이터 모델"""
    id: str                       # 기사 고유 해시 (SHA-256 / MD5 기반)
    chapter_id: str               # 소속 챕터 ID
    chapter_name: str             # 소속 챕터 한글명
    title: str                    # 기사 제목
    link: str                     # 원문 URL
    source: str                   # 언론사 / 매체명
    published_at: str             # 발행 일시 (ISO 형식 또는 읽기 쉬운 형식)
    summary_raw: str              # 원문 요약 또는 발췌문
    editorial: EditorialContent   # 심층 에디토리얼 분석
    keywords: List[str] = field(default_factory=list) # 핵심 키워드 (3~5개)
    importance_score: float = 5.0 # 중요도 점수 (1.0 ~ 10.0)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class ChapterBundle:
    """단일 챕터 번들 (정확히 10개 기사)"""
    id: str
    name: str
    name_en: str
    icon: str
    description: str
    count: int
    articles: List[Article]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "name_en": self.name_en,
            "icon": self.icon,
            "description": self.description,
            "count": self.count,
            "articles": [a.to_dict() if isinstance(a, Article) else a for a in self.articles]
        }


@dataclass
class WeatherData:
    """인천 서구 검단 지역 날씨 정보"""
    location: str                 # "인천 서구 검단"
    temp_current: float           # 현재 기온 (℃)
    temp_min: float               # 오늘 최저 기온 (℃)
    temp_max: float               # 오늘 최고 기온 (℃)
    condition: str                # 날씨 상태 (맑음, 구름많음, 비 등)
    condition_icon: str           # 날씨 이모지/아이콘
    precipitation_prob: int       # 강수 확률 (%)
    humidity: Optional[int] = None # 습도 (%)
    air_quality: str = "보통"     # 대기질
    clothing_tip: str = "가벼운 외투를 챙기세요." # 옷차림 팁

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrendingKeyword:
    """실시간 트렌드 키워드"""
    keyword: str
    count: int
    category: str
    sentiment: str = "neutral"   # positive, neutral, negative

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BriefingBundle:
    """최종 브리핑 종합 번들 (today.json)"""
    metadata: Dict[str, Any]
    weather: WeatherData
    three_line_summary: List[str]
    top_5_highlights: List[Article]
    trending_keywords: List[TrendingKeyword]
    chapters: List[ChapterBundle]
    youtube_hot_issues: List[Dict[str, Any]] = field(default_factory=list)
    integrity_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata,
            "weather": self.weather.to_dict() if isinstance(self.weather, WeatherData) else self.weather,
            "three_line_summary": self.three_line_summary,
            "top_5_highlights": [a.to_dict() if isinstance(a, Article) else a for a in self.top_5_highlights],
            "trending_keywords": [k.to_dict() if isinstance(k, TrendingKeyword) else k for k in self.trending_keywords],
            "chapters": [c.to_dict() if isinstance(c, ChapterBundle) else c for c in self.chapters],
            "youtube_hot_issues": self.youtube_hot_issues,
            "integrity_hash": self.integrity_hash
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
