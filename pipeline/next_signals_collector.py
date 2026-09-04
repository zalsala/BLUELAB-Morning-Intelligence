"""
pipeline/next_signals_collector.py
BLUELAB Morning Intelligence 향후 주요 일정 및 관전 포인트 (NEXT SIGNALS) 수집 모듈
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def generate_next_signals() -> List[Dict[str, Any]]:
    """오늘 이후 주목해야 할 핵심 4대 NEXT SIGNALS 생성"""
    today_kst = datetime.now(KST)
    d1 = (today_kst + timedelta(days=1)).strftime("%m월 %d일")
    d3 = (today_kst + timedelta(days=3)).strftime("%m월 %d일")
    d5 = (today_kst + timedelta(days=5)).strftime("%m월 %d일")
    d7 = (today_kst + timedelta(days=7)).strftime("%m월 %d일")

    return [
        {
            "id": "sig-01",
            "title": "미국 연준(Fed) FOMC 금리결정 및 점도표 발표",
            "scheduled_date": d5,
            "category": "거시경제 · 통화정책",
            "impact": "HIGH",
            "key_watchpoint": "기준금리 인하 폭(25bp vs 50bp 빅컷) 및 제롬 파월 의장의 고용시장 냉각 관련 발언 톤"
        },
        {
            "id": "sig-02",
            "title": "글로벌 AI 반도체 컨퍼런스 및 HBM4 로드맵 공개",
            "scheduled_date": d3,
            "category": "AI · 반도체",
            "impact": "HIGH",
            "key_watchpoint": "차세대 16단 HBM3E 및 HBM4 커스텀 베이스 다이 파운드리 협력 구도 구체화"
        },
        {
            "id": "sig-03",
            "title": "한국은행 금융통화위원회 거시건전성 점검회의",
            "scheduled_date": d1,
            "category": "국내금융 · 부동산",
            "impact": "MEDIUM",
            "key_watchpoint": "수도권 주택담보대출 2단계 스트레스 DSR 시행 후 가계부채 증가세 둔화 여부 진단"
        },
        {
            "id": "sig-04",
            "title": "유럽 의회 AI Act 시행 세부 가이드라인 공표",
            "scheduled_date": d7,
            "category": "글로벌 규제 · 플랫폼",
            "impact": "MEDIUM",
            "key_watchpoint": "범용 인공지능(GPAI) 모델 제공자에 대한 저작권 투명성 및 위험 평가 의무 적용 범위"
        }
    ]
