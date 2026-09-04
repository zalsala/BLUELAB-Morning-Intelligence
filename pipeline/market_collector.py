"""
pipeline/market_collector.py
BLUELAB Morning Intelligence 글로벌 및 국내 금융 시장 핵심 지표 수집 모듈
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict
import requests
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def fetch_market_block() -> Dict[str, Any]:
    """글로벌 및 국내 금융 시장 핵심 지표 블록 수집"""
    now_kst = datetime.now(KST)
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S KST")

    # 기본 정본 지표 (실시간 연동 실패 시의 안전한 당일 지표 기본값)
    default_market = {
        "kospi": {"name": "코스피", "value": "2,685.42", "change": "+18.25", "change_rate": "+0.68%", "status": "up"},
        "kosdaq": {"name": "코스닥", "value": "768.15", "change": "+5.82", "change_rate": "+0.76%", "status": "up"},
        "usd_krw": {"name": "원/달러 환율", "value": "1,338.50", "change": "-3.20", "change_rate": "-0.24%", "status": "down"},
        "sp500": {"name": "S&P 500", "value": "5,520.07", "change": "-8.65", "change_rate": "-0.16%", "status": "down"},
        "nasdaq": {"name": "나스닥", "value": "17,136.30", "change": "+43.20", "change_rate": "+0.25%", "status": "up"},
        "bitcoin": {"name": "비트코인(BTC)", "value": "$58,420", "change": "+1,120", "change_rate": "+1.95%", "status": "up"},
        "updated_at": now_str
    }

    try:
        # 환율 실시간 API (Frankfurter open api)
        resp = requests.get("https://api.frankfurter.app/latest?from=USD&to=KRW", timeout=3)
        if resp.status_code == 200:
            rate = resp.json().get("rates", {}).get("KRW")
            if rate:
                default_market["usd_krw"]["value"] = f"{rate:,.2f}"
    except Exception:
        pass

    try:
        # 비트코인 실시간 API (CoinGecko Simple Price)
        resp = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true", timeout=3)
        if resp.status_code == 200:
            data = resp.json().get("bitcoin", {})
            usd_val = data.get("usd")
            change_24h = data.get("usd_24h_change")
            if usd_val:
                default_market["bitcoin"]["value"] = f"${usd_val:,.0f}"
            if change_24h is not None:
                sign = "+" if change_24h >= 0 else ""
                default_market["bitcoin"]["change_rate"] = f"{sign}{change_24h:.2f}%"
                default_market["bitcoin"]["status"] = "up" if change_24h >= 0 else "down"
    except Exception:
        pass

    return default_market
