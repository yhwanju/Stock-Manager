from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from config import (
    CASH_RECOMMENDATIONS,
    DEFAULT_THEMES,
    DISCORD_CONTENT_LIMIT,
    HISTORY_INTERVAL,
    HISTORY_PERIOD,
    HOLDINGS_FILE,
    KST,
    MARKET_INDEXES,
    MARKET_STRATEGIES,
    NEWS_SUMMARY_FILE,
    STOCKS_FILE,
    THEME_KEYWORDS,
    WEBHOOK_ENV_NAME,
)


BASE_DIR = Path(__file__).resolve().parent


@dataclass
class StockAnalysis:
    name: str
    ticker: str
    themes: list[str] = field(default_factory=list)
    current_price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    quant_score: int = 0
    timing_score: int = 0
    final_action: str = "데이터 오류"
    current_state: str = "데이터 오류"
    entry_zone: str = "-"
    stop_price: float | None = None
    target_price: float | None = None
    reason: str = "시세 데이터를 수집하지 못했습니다."
    error: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def composite_score(self) -> int:
        return round(self.quant_score * 0.55 + self.timing_score * 0.45)


@dataclass
class MarketSummary:
    state: str
    cash_recommendation: str
    strategy: str
    reasons: list[str]


def load_json_file(file_name: str, default: Any) -> Any:
    path = BASE_DIR / file_name
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        print(f"{file_name} JSON 파싱 오류: {exc}")
        return default


def clamp(value: float, minimum: int = 0, maximum: int = 100) -> int:
    if math.isnan(value) or math.isinf(value):
        return minimum
    return round(max(minimum, min(maximum, value)))


def format_krw(value: float | int | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return f"{float(value):,.0f}원"


def format_pct(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return f"{value:+.2f}%"


def normalize_text(value: str) -> str:
    return value.lower().replace(" ", "").replace("/", "")


def fetch_history(ticker: str) -> pd.DataFrame:
    data = yf.Ticker(ticker).history(
        period=HISTORY_PERIOD,
        interval=HISTORY_INTERVAL,
        auto_adjust=False,
    )
    if data.empty:
        raise ValueError("시세 데이터가 비어 있습니다.")
    if "Close" not in data.columns:
        raise ValueError("종가 컬럼을 찾지 못했습니다.")
    return data.dropna(subset=["Close"])


def latest_float(series: pd.Series, default: float | None = None) -> float | None:
    clean = series.dropna()
    if clean.empty:
        return default
    value = float(clean.iloc[-1])
    if not math.isfinite(value):
        return default
    return value


def calculate_rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) <= period:
        return 50.0

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    latest_rsi = latest_float(rsi)
    latest_loss = latest_float(avg_loss)
    latest_gain = latest_float(avg_gain)
    if latest_rsi is not None:
        return latest_rsi
    if latest_loss == 0 and latest_gain and latest_gain > 0:
        return 100.0
    return 50.0


def score_theme_bonus(stock_themes: list[str], strong_themes: list[str]) -> int:
    normalized_strong = [normalize_text(theme) for theme in strong_themes]
    for stock_theme in stock_themes:
        normalized_stock = normalize_text(stock_theme)
        if any(
            normalized_stock in strong_theme or strong_theme in normalized_stock
            for strong_theme in normalized_strong
        ):
            return 5
    return 0


def choose_final_action(analysis: StockAnalysis, market_state: str) -> str:
    score = analysis.composite_score
    quant = analysis.quant_score
    timing = analysis.timing_score

    if analysis.error:
        return "데이터 오류로 신규 매매 금지"

    if market_state == "하락장":
        if score >= 85 and timing >= 75:
            return "소액 분할매수 후보"
        return "관망 / 현금 확보"

    if market_state == "변동성 확대장":
        if quant >= 78 and timing >= 72:
            return "선별 분할매수"
        return "관망"

    if market_state == "횡보장":
        if score >= 75 and timing >= 70:
            return "짧은 스윙 매수 후보"
        if score >= 60:
            return "관망 후 눌림 대기"
        return "매매 금지"

    if score >= 80 and timing >= 70:
        return "매수 가능"
    if score >= 65:
        return "분할매수 검토"
    if score >= 50:
        return "관망"
    return "매매 금지"


def describe_current_state(
    price: float,
    ma5: float,
    ma20: float,
    ma60: float,
    rsi: float,
    volume_ratio: float,
) -> str:
    if rsi >= 75 and volume_ratio >= 2:
        return "단기 과열"
    if price > ma5 > ma20 > ma60:
        return "상승 추세"
    if price > ma20 and ma5 > ma20:
        return "추세 양호"
    if price < ma20 and ma5 < ma20:
        return "약세"
    return "중립"


def build_reason(
    analysis: StockAnalysis,
    ma20: float,
    ma60: float,
    rsi: float,
    volume_ratio: float,
    theme_bonus: int,
) -> str:
    parts = [
        f"20일선 대비 {format_pct(analysis.metrics.get('price_vs_ma20'))}",
        f"RSI {rsi:.1f}",
        f"거래량 {volume_ratio:.1f}배",
    ]
    if analysis.current_price and analysis.current_price > ma20 > ma60:
        parts.append("중기 추세 우위")
    if theme_bonus:
        parts.append("뉴스 테마 가점")
    return ", ".join(parts)


def analyze_stock(stock: dict[str, Any], strong_themes: list[str], market_state: str) -> StockAnalysis:
    name = stock["name"]
    ticker = stock["ticker"]
    themes = stock.get("themes", [])
    analysis = StockAnalysis(name=name, ticker=ticker, themes=themes)

    try:
        history = fetch_history(ticker)
        close = history["Close"].astype(float)
        volume = history["Volume"].astype(float) if "Volume" in history.columns else pd.Series(dtype=float)

        price = latest_float(close)
        previous_close = float(close.dropna().iloc[-2]) if len(close.dropna()) >= 2 else price
        if price is None or previous_close is None:
            raise ValueError("최근 종가를 계산하지 못했습니다.")

        ma5 = latest_float(close.rolling(5, min_periods=3).mean(), price) or price
        ma20 = latest_float(close.rolling(20, min_periods=5).mean(), price) or price
        ma60 = latest_float(close.rolling(60, min_periods=20).mean(), ma20) or ma20
        rsi = calculate_rsi(close)
        returns = close.pct_change().dropna()
        volatility20 = latest_float(returns.rolling(20, min_periods=5).std(), 0.0) or 0.0
        momentum20 = ((price / float(close.iloc[-21])) - 1) * 100 if len(close) >= 21 else 0.0
        change_pct = ((price / previous_close) - 1) * 100 if previous_close else 0.0

        avg_volume20 = latest_float(volume.rolling(20, min_periods=5).mean(), 0.0) or 0.0
        latest_volume = latest_float(volume, 0.0) or 0.0
        volume_ratio = latest_volume / avg_volume20 if avg_volume20 > 0 else 1.0
        price_vs_ma20 = ((price / ma20) - 1) * 100 if ma20 else 0.0

        trend_score = 0
        trend_score += 20 if ma20 > ma60 else 8 if ma20 >= ma60 * 0.98 else 0
        trend_score += 15 if ma5 > ma20 else 5 if ma5 >= ma20 * 0.99 else 0
        trend_score += 10 if price > ma20 else 4 if price >= ma20 * 0.98 else 0

        momentum_score = max(0, min(20, momentum20 + 10))
        volume_score = 15 if 1.2 <= volume_ratio <= 4 else 8 if volume_ratio > 4 else 5 if volume_ratio >= 0.8 else 0
        volatility_score = 10 if volatility20 <= 0.035 else 5 if volatility20 <= 0.06 else 0
        theme_bonus = score_theme_bonus(themes, strong_themes)

        quant_score = clamp(
            trend_score + momentum_score + volume_score + volatility_score + theme_bonus
        )

        timing_score = 0
        timing_score += 25 if 45 <= rsi <= 65 else 15 if 35 <= rsi < 45 else 10 if 65 < rsi <= 70 else 5 if rsi < 35 else 0
        timing_score += 25 if price > ma5 > ma20 else 12 if price > ma20 else 5 if price >= ma20 * 0.97 else 0
        timing_score += 20 if 1.2 <= volume_ratio <= 3 else 8 if volume_ratio > 3 else 5 if volume_ratio >= 0.8 else 0
        timing_score += 15 if -1 <= change_pct <= 5 else 5 if -3 <= change_pct < -1 else 0
        if change_pct >= 8 or rsi >= 78:
            timing_score -= 15

        timing_score = clamp(timing_score)

        stop_price = max(price * 0.92, ma20 * 0.95)
        if stop_price >= price:
            stop_price = price * 0.93
        target_multiplier = 1.12 if market_state == "상승장" else 1.08
        target_price = price * target_multiplier
        entry_low = min(price * 0.985, ma5 * 0.995)
        entry_high = price * (1.015 if timing_score >= 70 else 1.0)

        analysis.current_price = price
        analysis.previous_close = previous_close
        analysis.change_pct = change_pct
        analysis.quant_score = quant_score
        analysis.timing_score = timing_score
        analysis.current_state = describe_current_state(price, ma5, ma20, ma60, rsi, volume_ratio)
        analysis.entry_zone = f"{format_krw(entry_low)} ~ {format_krw(entry_high)}"
        analysis.stop_price = stop_price
        analysis.target_price = target_price
        analysis.metrics = {
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "rsi": rsi,
            "volume_ratio": volume_ratio,
            "volatility20": volatility20,
            "momentum20": momentum20,
            "price_vs_ma20": price_vs_ma20,
        }
        analysis.final_action = choose_final_action(analysis, market_state)
        analysis.reason = build_reason(analysis, ma20, ma60, rsi, volume_ratio, theme_bonus)
        return analysis
    except Exception as exc:
        analysis.error = str(exc)
        analysis.reason = f"데이터 수집 실패: {exc}"
        analysis.final_action = "데이터 오류로 신규 매매 금지"
        return analysis


def analyze_market() -> MarketSummary:
    snapshots: list[dict[str, Any]] = []
    errors: list[str] = []

    for index in MARKET_INDEXES:
        try:
            history = fetch_history(index["ticker"])
            close = history["Close"].astype(float)
            price = latest_float(close)
            if price is None:
                raise ValueError("최근 지수 종가 없음")

            ma20 = latest_float(close.rolling(20, min_periods=5).mean(), price) or price
            returns = close.pct_change().dropna()
            volatility20 = latest_float(returns.rolling(20, min_periods=5).std(), 0.0) or 0.0
            return5 = ((price / float(close.iloc[-6])) - 1) * 100 if len(close) >= 6 else 0.0
            return20 = ((price / float(close.iloc[-21])) - 1) * 100 if len(close) >= 21 else 0.0

            snapshots.append(
                {
                    "name": index["name"],
                    "price": price,
                    "above_ma20": price > ma20,
                    "return5": return5,
                    "return20": return20,
                    "volatility20": volatility20,
                }
            )
        except Exception as exc:
            errors.append(f"{index['name']} 오류: {exc}")

    if not snapshots:
        state = "횡보장"
        return MarketSummary(
            state=state,
            cash_recommendation=CASH_RECOMMENDATIONS[state],
            strategy=MARKET_STRATEGIES[state],
            reasons=["시장 지수 수집 실패로 보수적 중립 판단"] + errors,
        )

    avg_return5 = float(np.mean([item["return5"] for item in snapshots]))
    avg_return20 = float(np.mean([item["return20"] for item in snapshots]))
    avg_volatility = float(np.mean([item["volatility20"] for item in snapshots]))
    above_ratio = sum(1 for item in snapshots if item["above_ma20"]) / len(snapshots)

    if avg_return20 <= -3 and above_ratio < 0.5:
        state = "하락장"
    elif avg_volatility >= 0.018 or (abs(avg_return5) >= 3.5 and above_ratio < 1):
        state = "변동성 확대장"
    elif avg_return20 >= 2 and avg_return5 >= 0 and above_ratio >= 0.5:
        state = "상승장"
    else:
        state = "횡보장"

    reasons = [
        f"5일 평균 등락률 {avg_return5:+.2f}%",
        f"20일 평균 등락률 {avg_return20:+.2f}%",
        f"20일 변동성 {avg_volatility * 100:.2f}%",
        f"20일선 상회 지수 비율 {above_ratio * 100:.0f}%",
    ]
    reasons.extend(errors)

    return MarketSummary(
        state=state,
        cash_recommendation=CASH_RECOMMENDATIONS[state],
        strategy=MARKET_STRATEGIES[state],
        reasons=reasons,
    )


def extract_themes_from_news(news_summary: dict[str, Any]) -> tuple[list[str], str]:
    weighted: dict[str, int] = {}
    explicit_themes = news_summary.get("themes", [])
    key_news = news_summary.get("key_news", [])

    def add_theme(theme: str, weight: int = 3) -> None:
        if not theme:
            return
        weighted[theme] = weighted.get(theme, 0) + weight

    def parse_weight(value: Any, default: int = 3) -> int:
        try:
            return max(1, int(float(value)))
        except (TypeError, ValueError):
            return default

    for item in explicit_themes:
        if isinstance(item, dict):
            add_theme(str(item.get("name") or item.get("theme") or ""), parse_weight(item.get("score")))
        else:
            add_theme(str(item), 3)

    news_texts: list[str] = []
    for item in key_news:
        if isinstance(item, dict):
            text = " ".join(str(item.get(key, "")) for key in ("title", "summary", "content"))
            news_texts.append(text)
            for theme in item.get("themes", []):
                add_theme(str(theme), 2)
        else:
            news_texts.append(str(item))

    combined_news = " ".join(news_texts)
    for theme, keywords in THEME_KEYWORDS.items():
        matches = sum(1 for keyword in keywords if keyword.lower() in combined_news.lower())
        if matches:
            add_theme(theme, matches)

    if not weighted:
        return DEFAULT_THEMES[:3], "뉴스 연동 파일이 비어 있어 기본 관심 테마를 사용했습니다."

    ranked = sorted(weighted.items(), key=lambda item: item[1], reverse=True)
    return [theme for theme, _ in ranked[:3]], "뉴스 요약 파일을 반영했습니다."


def holding_action(analysis: StockAnalysis, quantity: int, average_price: float, market_state: str) -> tuple[str, float | None, float | None]:
    if analysis.error or analysis.current_price is None:
        return "데이터 오류로 보유 판단 보류", None, None

    current_price = analysis.current_price
    profit_pct = ((current_price / average_price) - 1) * 100
    technical_stop = analysis.stop_price or current_price * 0.92
    stop_price = max(average_price * 0.92, technical_stop)
    if stop_price >= current_price:
        stop_price = min(current_price * 0.97, average_price * 0.92)
    target_price = max(average_price * 1.15, current_price * 1.08)

    if current_price <= stop_price or profit_pct <= -8:
        action = "손절 기준 점검"
    elif profit_pct >= 15:
        action = "분할 익절"
    elif market_state == "하락장" and profit_pct < 0:
        action = "비중 축소 / 현금 확보"
    elif analysis.timing_score >= 70 and analysis.quant_score >= 65:
        action = "보유"
    else:
        action = "관망"

    _ = quantity
    return action, stop_price, target_price


def make_report(
    market: MarketSummary,
    strong_themes: list[str],
    theme_note: str,
    watchlist: list[StockAnalysis],
    holdings: list[dict[str, Any]],
    holding_analyses: dict[str, StockAnalysis],
) -> str:
    now = datetime.now(KST)
    recommendation_pool = [item for item in watchlist if not item.error]
    recommendations = sorted(
        recommendation_pool,
        key=lambda item: (item.composite_score, item.timing_score, item.quant_score),
        reverse=True,
    )[:3]

    lines: list[str] = []
    lines.append("[주식관리 리포트]")
    lines.append(f"발송일: {now:%Y-%m-%d %H:%M} KST")
    lines.append(f"시장 상태: {market.state} ({market.strategy})")
    lines.append(f"현금 비중 권고: {market.cash_recommendation}")
    lines.append(f"시장 판단 근거: {' / '.join(market.reasons)}")
    lines.append("")

    lines.append("[오늘 강한 테마]")
    for index, theme in enumerate(strong_themes[:3], start=1):
        lines.append(f"{index}. {theme}")
    lines.append(f"참고: {theme_note}")
    lines.append("")

    lines.append("[추천 종목 TOP 3]")
    if recommendations:
        for item in recommendations:
            lines.append(f"종목명: {item.name} ({item.ticker})")
            lines.append(f"퀀트 점수: {item.quant_score}")
            lines.append(f"매매 타이밍 점수: {item.timing_score}")
            lines.append(f"최종 액션: {item.final_action}")
            lines.append(f"진입 가능 구간: {item.entry_zone}")
            lines.append(f"손절 구간: {format_krw(item.stop_price)}")
            lines.append(f"목표가: {format_krw(item.target_price)}")
            lines.append(f"근거: {item.reason}")
            lines.append("")
    else:
        lines.append("추천 가능 종목 없음: 관심종목 시세 수집 실패")
        lines.append("")

    lines.append("[관심종목 점검]")
    for item in watchlist:
        lines.append(f"종목명: {item.name} ({item.ticker})")
        lines.append(f"현재 상태: {item.current_state}")
        lines.append(f"액션: {item.final_action}")
        if item.error:
            lines.append(f"오류: {item.error}")
        lines.append("")

    lines.append("[보유종목 관리]")
    action_summaries: list[str] = []
    for holding in holdings:
        ticker = holding["ticker"]
        analysis = holding_analyses[ticker]
        quantity = int(holding["quantity"])
        average_price = float(holding["average_price"])
        action, stop_price, target_price = holding_action(analysis, quantity, average_price, market.state)
        profit_pct = None
        if analysis.current_price:
            profit_pct = ((analysis.current_price / average_price) - 1) * 100

        lines.append(f"종목명: {holding['name']} ({ticker})")
        lines.append(f"보유수량: {quantity:,}주")
        lines.append(f"평단: {format_krw(average_price)}")
        lines.append(f"현재가: {format_krw(analysis.current_price)}")
        lines.append(f"수익률: {format_pct(profit_pct)}")
        lines.append(f"손절가: {format_krw(stop_price)}")
        lines.append(f"목표가: {format_krw(target_price)}")
        lines.append(f"액션: {action}")
        action_summaries.append(f"- {holding['name']}: {action}")
        if analysis.error:
            lines.append(f"오류: {analysis.error}")
        lines.append("")

    lines.append("[손절/익절/관망 액션]")
    lines.extend(action_summaries or ["- 점검 가능한 보유종목 없음"])
    lines.append("")

    lines.append("[오늘의 매매 금지 조건]")
    lines.append("- 추격매수 금지")
    lines.append("- 하락장에서는 현금 50% 이상")
    lines.append("- 변동성 확대장에서는 확실한 종목만 매매")
    lines.append("- 손절가 이탈 종목 물타기 금지")
    lines.append("- 데이터 오류 종목은 신규 매수 금지")

    return "\n".join(lines)


def split_discord_message(report: str, limit: int = DISCORD_CONTENT_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""

    for block in report.split("\n\n"):
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(block) <= limit:
            current = block
            continue

        lines = block.splitlines()
        for line in lines:
            candidate_line = f"{current}\n{line}".strip() if current else line
            if len(candidate_line) > limit and current:
                chunks.append(current)
                current = line
            else:
                current = candidate_line

    if current:
        chunks.append(current)

    if len(chunks) <= 1:
        return chunks

    return [f"[{index}/{len(chunks)}]\n{chunk}" for index, chunk in enumerate(chunks, start=1)]


def send_to_discord(report: str, webhook_url: str) -> None:
    chunks = split_discord_message(report)
    for chunk in chunks:
        response = requests.post(
            webhook_url,
            json={
                "content": chunk,
                "allowed_mentions": {"parse": []},
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Discord 전송 실패: HTTP {response.status_code} {response.text}")


def build_report_from_files() -> str:
    stocks = load_json_file(STOCKS_FILE, [])
    holdings = load_json_file(HOLDINGS_FILE, [])
    news_summary = load_json_file(NEWS_SUMMARY_FILE, {})

    market = analyze_market()
    strong_themes, theme_note = extract_themes_from_news(news_summary)

    watchlist = [analyze_stock(stock, strong_themes, market.state) for stock in stocks]

    holding_analyses = {
        holding["ticker"]: analyze_stock(holding, strong_themes, market.state)
        for holding in holdings
    }

    return make_report(
        market=market,
        strong_themes=strong_themes,
        theme_note=theme_note,
        watchlist=watchlist,
        holdings=holdings,
        holding_analyses=holding_analyses,
    )


def is_weekend_kst(now: datetime) -> bool:
    return now.weekday() >= 5


def main() -> int:
    parser = argparse.ArgumentParser(description="데일리 주식관리 리포트 생성 및 Discord 발송")
    parser.add_argument("--dry-run", action="store_true", help="Discord 전송 없이 리포트만 출력합니다.")
    parser.add_argument("--force-weekend", action="store_true", help="주말에도 강제로 실행합니다.")
    args = parser.parse_args()

    now = datetime.now(KST)
    dry_run = args.dry_run or os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}

    if is_weekend_kst(now) and not args.force_weekend:
        print(f"{now:%Y-%m-%d} KST는 주말입니다. 리포트 발송을 건너뜁니다.")
        return 0

    report = build_report_from_files()
    print(report)

    if dry_run:
        print("\nDRY_RUN 모드이므로 Discord 전송을 건너뜁니다.")
        return 0

    webhook_url = os.getenv(WEBHOOK_ENV_NAME)
    if not webhook_url:
        raise RuntimeError(f"{WEBHOOK_ENV_NAME} 환경 변수가 설정되어 있지 않습니다.")

    send_to_discord(report, webhook_url)
    print("Discord 전송 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
