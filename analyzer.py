from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import numpy as np
import pandas as pd
import yfinance as yf

import storage
from config import (
    CASH_RECOMMENDATIONS,
    DEFAULT_THEMES,
    HISTORY_INTERVAL,
    HISTORY_PERIOD,
    KST,
    MARKET_INDEXES,
    MARKET_STRATEGIES,
    THEME_KEYWORDS,
)


Logger = Callable[[str], None] | None
KRX_LISTING_CACHE: pd.DataFrame | None = None


@dataclass
class TargetPriceLevel:
    label: str
    price: float | None
    emoji: str


@dataclass
class TargetPriceAnalysis:
    levels: list[TargetPriceLevel] = field(default_factory=list)
    most_realistic_label: str = "-"
    extension_note: str = "강한 테마 지속 시 최종 목표가 가능"
    condition_score: int = 0


@dataclass
class StockAnalysis:
    name: str
    ticker: str
    themes: list[str] = field(default_factory=list)
    subthemes: list[str] = field(default_factory=list)
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
    target_analysis: TargetPriceAnalysis = field(default_factory=TargetPriceAnalysis)
    reason: str = "시세 데이터를 수집하지 못했습니다."
    reason_bullets: list[str] = field(default_factory=list)
    risk_bullets: list[str] = field(default_factory=list)
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


@dataclass
class AnalysisContext:
    market: MarketSummary
    strong_themes: list[str]
    theme_note: str
    watchlist_items: list[dict[str, Any]]
    holdings: list[dict[str, Any]]
    news_summary: dict[str, Any]
    theme_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class TickerResolution:
    query: str
    name: str
    ticker: str
    search_method: str
    market: str = ""


def log(logger: Logger, message: str) -> None:
    if logger:
        logger(message)


def clamp(value: float, minimum: int = 0, maximum: int = 100) -> int:
    if math.isnan(value) or math.isinf(value):
        return minimum
    return round(max(minimum, min(maximum, value)))


def format_krw(value: float | int | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return f"{float(value):,.0f}원"


def is_korean_stock_ticker(ticker: str | None) -> bool:
    return str(ticker or "").upper().endswith((".KS", ".KQ"))


def format_price_for_ticker(value: float | int | None, ticker: str | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    if is_korean_stock_ticker(ticker):
        return format_krw(value)
    return f"${float(value):,.2f}"


def format_pct(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return f"{value:+.2f}%"


def holding_average_price(holding: dict[str, Any]) -> float:
    return float(holding.get("avg_price", holding.get("average_price", 0)) or 0)


def bold(value: Any) -> str:
    return f"**{value}**"


def section(title: str) -> list[str]:
    return [
        "━━━━━━━━━━",
        f"**{title}**",
        "━━━━━━━━━━",
        "",
    ]


def normalize_text(value: str) -> str:
    return value.lower().replace(" ", "").replace("/", "")


def priority_theme_names(theme_config: dict[str, Any]) -> list[str]:
    priority = theme_config.get("priority_themes", {})
    if isinstance(priority, dict) and priority:
        return list(priority.keys())
    return DEFAULT_THEMES[:]


def canonical_theme(theme: str, theme_config: dict[str, Any] | None = None) -> str:
    config = theme_config or storage.load_theme_config()
    cleaned = str(theme).strip()
    if not cleaned:
        return cleaned

    normalized = normalize_text(cleaned)
    for priority_theme in priority_theme_names(config):
        if normalize_text(priority_theme) == normalized:
            return priority_theme

    aliases = config.get("aliases", {})
    if isinstance(aliases, dict):
        for alias, target in aliases.items():
            if normalize_text(str(alias)) == normalized:
                return str(target)

    priority = config.get("priority_themes", {})
    if isinstance(priority, dict):
        for priority_theme, meta in priority.items():
            subthemes = meta.get("subthemes", []) if isinstance(meta, dict) else []
            for subtheme in subthemes:
                if normalize_text(str(subtheme)) == normalized:
                    return str(priority_theme)

    return cleaned


def is_priority_theme(theme: str, theme_config: dict[str, Any] | None = None) -> bool:
    config = theme_config or storage.load_theme_config()
    canonical = canonical_theme(theme, config)
    return canonical in priority_theme_names(config)


def split_theme_values(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value).split(",")
    return [str(item).strip() for item in raw_values if str(item).strip()]


def resolve_theme_inputs(value: str | list[str] | None, theme_config: dict[str, Any] | None = None) -> tuple[list[str], list[str], list[str]]:
    config = theme_config or storage.load_theme_config()
    priority = priority_theme_names(config)
    themes: list[str] = []
    subthemes: list[str] = []
    non_priority: list[str] = []

    priority_meta = config.get("priority_themes", {})
    for raw_theme in split_theme_values(value):
        canonical = canonical_theme(raw_theme, config)
        if canonical in priority:
            if canonical not in themes:
                themes.append(canonical)
            meta = priority_meta.get(canonical, {}) if isinstance(priority_meta, dict) else {}
            for subtheme in meta.get("subthemes", []) if isinstance(meta, dict) else []:
                if normalize_text(raw_theme) == normalize_text(str(subtheme)) and raw_theme not in subthemes:
                    subthemes.append(raw_theme)
        else:
            if raw_theme not in non_priority:
                non_priority.append(raw_theme)
            if raw_theme not in themes:
                themes.append(raw_theme)

    return themes, subthemes, non_priority


def normalize_stock_theme_fields(stock: dict[str, Any], theme_config: dict[str, Any] | None = None) -> tuple[list[str], list[str], list[str]]:
    config = theme_config or storage.load_theme_config()
    raw_themes = stock.get("themes", [])
    raw_subthemes = stock.get("subthemes", [])
    themes, subthemes, non_priority = resolve_theme_inputs(raw_themes, config)
    for subtheme in split_theme_values(raw_subthemes):
        parent = canonical_theme(subtheme, config)
        if parent in priority_theme_names(config) and parent not in themes:
            themes.append(parent)
        if subtheme not in subthemes:
            subthemes.append(subtheme)
    for raw_theme in stock.get("non_priority_themes", []):
        if raw_theme not in non_priority:
            non_priority.append(raw_theme)
    return themes, subthemes, non_priority


def stock_theme_labels(stock: dict[str, Any], theme_config: dict[str, Any] | None = None) -> list[str]:
    themes, subthemes, non_priority = normalize_stock_theme_fields(stock, theme_config)
    return [*themes, *subthemes, *non_priority]


def stock_matches_theme(stock: dict[str, Any] | StockAnalysis, theme: str, theme_config: dict[str, Any] | None = None) -> bool:
    config = theme_config or storage.load_theme_config()
    target = canonical_theme(theme, config)
    source = {
        "themes": getattr(stock, "themes", None) if not isinstance(stock, dict) else stock.get("themes", []),
        "subthemes": getattr(stock, "subthemes", None) if not isinstance(stock, dict) else stock.get("subthemes", []),
        "non_priority_themes": [] if not isinstance(stock, dict) else stock.get("non_priority_themes", []),
    }
    labels = stock_theme_labels(source, config)
    return any(canonical_theme(label, config) == target or normalize_text(label) == normalize_text(theme) for label in labels)


def theme_representatives(theme_config: dict[str, Any] | None = None, themes: list[str] | None = None) -> list[dict[str, Any]]:
    config = theme_config or storage.load_theme_config()
    selected = themes or priority_theme_names(config)
    priority = config.get("priority_themes", {})
    representatives: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not isinstance(priority, dict):
        return representatives
    for theme in selected:
        canonical = canonical_theme(theme, config)
        meta = priority.get(canonical, {})
        if not isinstance(meta, dict):
            continue
        for item in meta.get("representatives", []):
            ticker = str(item.get("ticker", ""))
            if not ticker or ticker in seen:
                continue
            representatives.append(item)
            seen.add(ticker)
    return representatives


def contains_hangul(value: str) -> bool:
    return any("가" <= char <= "힣" for char in value)


def normalize_ticker_symbol(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    if text.isdigit() and len(text) == 6:
        return f"{text}.KS"
    if contains_hangul(text):
        return text
    return text.upper()


def looks_like_us_ticker(value: str) -> bool:
    text = value.strip().upper()
    if not text or contains_hangul(text):
        return False
    if text.isdigit():
        return False
    return len(text) <= 12 and all(char.isalnum() or char in {".", "-"} for char in text)


def yfinance_has_data(ticker: str) -> bool:
    try:
        history = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
        return not history.empty and "Close" in history.columns
    except Exception:
        return False


def krx_yfinance_suffix(market: str) -> str | None:
    normalized = str(market or "").upper()
    if "KOSDAQ" in normalized:
        return "KQ"
    if "KOSPI" in normalized:
        return "KS"
    return None


def load_krx_listing() -> pd.DataFrame | None:
    global KRX_LISTING_CACHE
    if KRX_LISTING_CACHE is not None:
        return KRX_LISTING_CACHE
    try:
        import FinanceDataReader as fdr

        listing = fdr.StockListing("KRX")
        if isinstance(listing, pd.DataFrame) and not listing.empty:
            KRX_LISTING_CACHE = listing
            return KRX_LISTING_CACHE
    except Exception:
        return None
    return None


def resolve_krx_ticker(query: str) -> TickerResolution | None:
    listing = load_krx_listing()
    if listing is None or listing.empty:
        return None

    name_column = "Name" if "Name" in listing.columns else None
    code_column = "Code" if "Code" in listing.columns else None
    market_column = "Market" if "Market" in listing.columns else None
    if not name_column or not code_column:
        return None

    if query.strip().isdigit():
        normalized_code = query.strip().zfill(6)
        matches = listing[listing[code_column].astype(str).str.zfill(6) == normalized_code]
    else:
        normalized_query = normalize_text(query)
        names = listing[name_column].astype(str).map(normalize_text)
        matches = listing[names == normalized_query]

    if matches.empty:
        return None

    for _, row in matches.iterrows():
        market = str(row.get(market_column, "")) if market_column else ""
        suffix = krx_yfinance_suffix(market)
        if not suffix:
            continue
        code = str(row[code_column]).zfill(6)
        return TickerResolution(
            query=query,
            name=str(row.get(name_column, query)),
            ticker=f"{code}.{suffix}",
            search_method="FinanceDataReader KRX 자동검색",
            market=market,
        )
    return None


def resolve_ticker(name_or_ticker: str) -> TickerResolution | None:
    query = name_or_ticker.strip()
    if not query:
        return None

    ticker_map = storage.load_ticker_map()
    normalized_query = storage.normalize(query)

    for name, ticker in ticker_map.items():
        if storage.normalize(name) == normalized_query:
            return TickerResolution(
                query=query,
                name=str(name),
                ticker=normalize_ticker_symbol(str(ticker)),
                search_method="ticker_map.json 종목명 매칭",
            )

    for name, ticker in ticker_map.items():
        normalized_ticker = storage.normalize(str(ticker))
        if normalized_ticker == normalized_query or (
            normalized_query.isdigit() and normalized_ticker.startswith(f"{normalized_query}.")
        ):
            display_name = query if not query.isdigit() else str(name)
            return TickerResolution(
                query=query,
                name=display_name,
                ticker=normalize_ticker_symbol(str(ticker)),
                search_method="ticker_map.json 티커 매칭",
            )

    krx_resolution = resolve_krx_ticker(query)
    if krx_resolution:
        return krx_resolution

    if looks_like_us_ticker(query):
        ticker = query.upper()
        if yfinance_has_data(ticker):
            return TickerResolution(
                query=query,
                name=ticker,
                ticker=ticker,
                search_method="yfinance 미국 티커 직접 조회",
            )

    return None


def resolve_ticker_from_map(query: str, ticker_map: dict[str, str]) -> str | None:
    normalized_query = normalize_text(query)
    for name, ticker in ticker_map.items():
        normalized_ticker = normalize_text(ticker)
        if normalize_text(name) == normalized_query:
            return normalize_ticker_symbol(ticker)
        if normalized_ticker == normalized_query:
            return normalize_ticker_symbol(ticker)
        if normalized_query.isdigit() and normalized_ticker.startswith(f"{normalized_query}."):
            return normalize_ticker_symbol(ticker)
    return None


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
        return "데이터 오류"

    if market_state == "하락장":
        if score >= 85 and timing >= 75:
            return "소액분할매수"
        return "관망"

    if market_state == "변동성 확대장":
        if quant >= 78 and timing >= 72:
            return "선별매수"
        return "관망"

    if market_state == "횡보장":
        if score >= 75 and timing >= 70:
            return "짧은스윙"
        if score >= 60:
            return "눌림대기"
        return "매매금지"

    if score >= 80 and timing >= 70:
        return "매수가능"
    if score >= 65:
        return "분할매수"
    if score >= 50:
        return "관망"
    return "매매금지"


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


def build_reason_bullets(
    analysis: StockAnalysis,
    ma20: float,
    ma60: float,
    rsi: float,
    volume_ratio: float,
    theme_bonus: int,
) -> list[str]:
    parts: list[str] = []

    if analysis.current_price and analysis.current_price > ma20 > ma60:
        parts.append("중기 추세 우위")
    elif analysis.current_price and analysis.current_price < ma20:
        parts.append("20일선 하회")
    else:
        parts.append("20일선 근처")

    if theme_bonus:
        parts.append("뉴스 테마 가점")

    if 1.2 <= volume_ratio <= 3:
        parts.append("거래량 양호")
    elif volume_ratio > 3:
        parts.append("거래량 과열")
    else:
        parts.append("거래량 보통")

    if 45 <= rsi <= 65:
        parts.append("RSI 중립")
    elif rsi > 70:
        parts.append("단기 과열")
    elif rsi < 35:
        parts.append("단기 침체")

    return parts[:4]


def build_risk_bullets(analysis: StockAnalysis, market_state: str) -> list[str]:
    risks: list[str] = []
    rsi = analysis.metrics.get("rsi")
    volume_ratio = analysis.metrics.get("volume_ratio")
    price_vs_ma20 = analysis.metrics.get("price_vs_ma20")

    if analysis.error:
        return ["데이터 오류로 신규매수 금지", "수동 확인 전 매매 보류", "시세 재조회 필요"]
    if market_state == "하락장":
        risks.append("하락장에서는 현금 비중 우선")
    if price_vs_ma20 is not None and price_vs_ma20 < -3:
        risks.append("20일선 하회로 추세 훼손 가능")
    if rsi is not None and rsi >= 70:
        risks.append("RSI 과열 구간")
    if volume_ratio is not None and volume_ratio > 3:
        risks.append("거래량 급증 후 변동성 확대 가능")

    risks.extend(["손절가 이탈 시 추세 훼손", "추격매수 금지", "분할 대응 필요"])
    return risks[:3]


def recent_high_value(high: pd.Series, fallback: float, days: int) -> float:
    values = high.dropna().tail(days)
    if values.empty:
        return fallback
    return float(values.max())


def target_condition_score(analysis: StockAnalysis, market_state: str, theme_bonus: int) -> int:
    metrics = analysis.metrics
    price = analysis.current_price or 0.0
    ma5 = metrics.get("ma5", price)
    ma20 = metrics.get("ma20", price)
    ma60 = metrics.get("ma60", ma20)
    volume_ratio = metrics.get("volume_ratio", 1.0)
    volatility20 = metrics.get("volatility20", 0.0)
    momentum20 = metrics.get("momentum20", 0.0)

    score = {
        "상승장": 20,
        "변동성 확대장": 10,
        "횡보장": 4,
        "하락장": -15,
    }.get(market_state, 0)

    score += 20 if analysis.quant_score >= 80 else 14 if analysis.quant_score >= 70 else 8 if analysis.quant_score >= 60 else 0
    score += 20 if analysis.timing_score >= 75 else 14 if analysis.timing_score >= 65 else 6 if analysis.timing_score >= 50 else -4
    score += 15 if theme_bonus > 0 else 0

    if 1.2 <= volume_ratio <= 3:
        score += 10
    elif 3 < volume_ratio <= 4.5:
        score += 4
    elif volume_ratio < 0.8:
        score -= 5

    if volatility20 <= 0.035:
        score += 8
    elif volatility20 <= 0.06:
        score += 2
    else:
        score -= 8

    if price > ma5 > ma20 > ma60:
        score += 15
    elif price > ma20 and ma20 >= ma60 * 0.98:
        score += 8
    elif price < ma20:
        score -= 8

    if momentum20 >= 8:
        score += 5
    elif momentum20 <= -5:
        score -= 5

    return clamp(score)


def select_target_extension_note(market_state: str, condition_score: int, theme_bonus: int) -> str:
    if market_state == "하락장":
        return "하락장에서는 최종 목표가는 확장 목표로만 관리"
    if market_state == "변동성 확대장":
        return "변동성 진정과 거래량 유지 시 최종 목표가 가능"
    if condition_score >= 82 and theme_bonus > 0:
        return "강한 테마와 거래량이 유지되면 최종 목표가 가능"
    if condition_score < 55:
        return "최종 목표가는 확장 목표로만 관리"
    return "강한 테마 지속 시 최종 목표가 가능"


def build_target_price_analysis(
    analysis: StockAnalysis,
    market_state: str,
    theme_bonus: int,
    recent_high_20: float,
    recent_high_60: float,
) -> TargetPriceAnalysis:
    price = analysis.current_price
    stop_price = analysis.stop_price
    if price is None or stop_price is None:
        return TargetPriceAnalysis()

    metrics = analysis.metrics
    ma20 = metrics.get("ma20", price)
    risk_unit = max(price - stop_price, price * 0.03)
    box_top = max(recent_high_20, ma20 * 1.05, price * 1.03)

    first_target = max(price + risk_unit, box_top)
    first_target = min(max(first_target, price * 1.03), price * 1.20)

    second_target = max(price + risk_unit * 2, first_target * 1.06, recent_high_60 * 1.03)
    second_target = min(second_target, price * 1.35)
    if second_target <= first_target:
        second_target = first_target * 1.06

    final_target = max(price + risk_unit * 3, second_target * 1.12, price * 1.20)
    final_target = min(final_target, price * 1.70)
    if final_target <= second_target:
        final_target = second_target * 1.10

    condition_score = target_condition_score(analysis, market_state, theme_bonus)
    volume_ratio = metrics.get("volume_ratio", 1.0)
    second_is_most_realistic = (
        market_state == "상승장"
        and theme_bonus > 0
        and analysis.quant_score >= 75
        and analysis.timing_score >= 60
        and volume_ratio >= 1.0
        and condition_score >= 75
    )

    if second_is_most_realistic:
        emojis = ["🟡", "🟢", "🔴"]
        most_realistic_label = "2차 목표가"
    else:
        emojis = ["🟢", "🟡", "🔴"]
        most_realistic_label = "1차 목표가"

    return TargetPriceAnalysis(
        levels=[
            TargetPriceLevel("1차 목표가", first_target, emojis[0]),
            TargetPriceLevel("2차 목표가", second_target, emojis[1]),
            TargetPriceLevel("최종 목표가", final_target, emojis[2]),
        ],
        most_realistic_label=most_realistic_label,
        extension_note=select_target_extension_note(market_state, condition_score, theme_bonus),
        condition_score=condition_score,
    )


def most_realistic_target_price(target_analysis: TargetPriceAnalysis) -> float | None:
    for level in target_analysis.levels:
        if level.label == target_analysis.most_realistic_label:
            return level.price
    if target_analysis.levels:
        return target_analysis.levels[0].price
    return None


def position_target_price_analysis(
    analysis: StockAnalysis,
    average_price: float,
    holding_target_price: float | None,
) -> TargetPriceAnalysis:
    base = analysis.target_analysis
    if not base.levels or holding_target_price is None:
        return base

    first_price = max(base.levels[0].price or 0.0, holding_target_price)
    second_price = max(base.levels[1].price or 0.0, first_price * 1.06, average_price * 1.22)
    final_price = max(base.levels[2].price or 0.0, second_price * 1.10, average_price * 1.35)

    return TargetPriceAnalysis(
        levels=[
            TargetPriceLevel(base.levels[0].label, first_price, base.levels[0].emoji),
            TargetPriceLevel(base.levels[1].label, second_price, base.levels[1].emoji),
            TargetPriceLevel(base.levels[2].label, final_price, base.levels[2].emoji),
        ],
        most_realistic_label=base.most_realistic_label,
        extension_note=base.extension_note,
        condition_score=base.condition_score,
    )


def analyze_stock(stock: dict[str, Any], strong_themes: list[str], market_state: str) -> StockAnalysis:
    name = stock["name"]
    ticker = stock["ticker"]
    themes, subthemes, _ = normalize_stock_theme_fields(stock)
    analysis = StockAnalysis(name=name, ticker=ticker, themes=themes, subthemes=subthemes)

    try:
        history = fetch_history(ticker)
        close = history["Close"].astype(float)
        high = history["High"].astype(float) if "High" in history.columns else close
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
        recent_high_20 = recent_high_value(high, price, 20)
        recent_high_60 = recent_high_value(high, recent_high_20, 60)

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
        entry_low = min(price * 0.985, ma5 * 0.995)
        entry_high = price * (1.015 if timing_score >= 70 else 1.0)

        analysis.current_price = price
        analysis.previous_close = previous_close
        analysis.change_pct = change_pct
        analysis.quant_score = quant_score
        analysis.timing_score = timing_score
        analysis.current_state = describe_current_state(price, ma5, ma20, ma60, rsi, volume_ratio)
        analysis.entry_zone = f"{format_price_for_ticker(entry_low, ticker)} ~ {format_price_for_ticker(entry_high, ticker)}"
        analysis.stop_price = stop_price
        analysis.metrics = {
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "rsi": rsi,
            "volume_ratio": volume_ratio,
            "volatility20": volatility20,
            "momentum20": momentum20,
            "price_vs_ma20": price_vs_ma20,
            "recent_high_20": recent_high_20,
            "recent_high_60": recent_high_60,
        }
        analysis.target_analysis = build_target_price_analysis(
            analysis=analysis,
            market_state=market_state,
            theme_bonus=theme_bonus,
            recent_high_20=recent_high_20,
            recent_high_60=recent_high_60,
        )
        analysis.target_price = most_realistic_target_price(analysis.target_analysis)
        analysis.final_action = choose_final_action(analysis, market_state)
        analysis.reason_bullets = build_reason_bullets(analysis, ma20, ma60, rsi, volume_ratio, theme_bonus)
        analysis.risk_bullets = build_risk_bullets(analysis, market_state)
        analysis.reason = " / ".join(analysis.reason_bullets)
        return analysis
    except Exception as exc:
        analysis.error = str(exc)
        analysis.reason = f"데이터 수집 실패: {exc}"
        analysis.reason_bullets = ["데이터 수집 실패"]
        analysis.risk_bullets = ["데이터 오류로 신규매수 금지", "수동 확인 전 매매 보류", "시세 재조회 필요"]
        analysis.final_action = "데이터 오류"
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
    theme_config = storage.load_theme_config()
    priority = priority_theme_names(theme_config)
    weighted: dict[str, int] = {}
    explicit_themes = news_summary.get("themes", [])
    key_news = news_summary.get("key_news", [])

    def add_theme(theme: str, weight: int = 3) -> None:
        if not theme:
            return
        canonical = canonical_theme(theme, theme_config)
        if canonical not in priority:
            return
        weighted[canonical] = weighted.get(canonical, 0) + weight

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
    keyword_map: dict[str, list[str]] = {}
    priority_meta = theme_config.get("priority_themes", {})
    for theme in priority:
        keyword_map[theme] = [theme]
        if isinstance(priority_meta, dict):
            meta = priority_meta.get(theme, {})
            if isinstance(meta, dict):
                keyword_map[theme].extend(str(item) for item in meta.get("subthemes", []))
    for theme, keywords in THEME_KEYWORDS.items():
        canonical = canonical_theme(theme, theme_config)
        if canonical in priority:
            keyword_map.setdefault(canonical, []).extend(keywords)

    for theme, keywords in keyword_map.items():
        matches = sum(1 for keyword in set(keywords) if keyword.lower() in combined_news.lower())
        if matches:
            add_theme(theme, matches)

    if not weighted:
        fallback = [theme for theme in DEFAULT_THEMES if theme in priority][:3] or priority[:3]
        return fallback, "뉴스 연동 파일이 비어 있어 우선 분석 테마 기본값을 사용했습니다."

    ranked = sorted(weighted.items(), key=lambda item: item[1], reverse=True)
    return [theme for theme, _ in ranked[:3]], "뉴스 요약 파일을 반영했습니다."


def holding_action(analysis: StockAnalysis, quantity: int, average_price: float, market_state: str) -> tuple[str, float | None, float | None]:
    if analysis.error or analysis.current_price is None:
        return "데이터 오류", None, None

    current_price = analysis.current_price
    profit_pct = ((current_price / average_price) - 1) * 100
    technical_stop = analysis.stop_price or current_price * 0.92
    stop_price = max(average_price * 0.92, technical_stop)
    if stop_price >= current_price:
        stop_price = min(current_price * 0.97, average_price * 0.92)
    target_price = max(average_price * 1.15, current_price * 1.08)

    if current_price <= stop_price or profit_pct <= -8:
        action = "손절주의"
    elif profit_pct >= 15:
        action = "일부익절"
    elif market_state == "하락장" and profit_pct < 0:
        action = "비중축소"
    elif analysis.timing_score >= 70 and analysis.quant_score >= 65:
        action = "보유"
    else:
        action = "관망"

    _ = quantity
    return action, stop_price, target_price


def summarize_holding_action(holdings: list[dict[str, Any]], holding_analyses: dict[str, StockAnalysis], market_state: str) -> str:
    actions: list[str] = []
    for holding in holdings:
        analysis = holding_analyses.get(holding["ticker"])
        if not analysis:
            continue
        action, _, _ = holding_action(
            analysis,
            int(holding["quantity"]),
            holding_average_price(holding),
            market_state,
        )
        actions.append(action)

    if any(action in {"손절주의", "비중축소"} for action in actions):
        return "리스크관리"
    if any(action == "일부익절" for action in actions):
        return "일부익절"
    if any(action == "보유" for action in actions):
        return "보유"
    return "관망"


def append_price_block(lines: list[str], label: str, value: float | int | None, ticker: str | None = None) -> None:
    lines.append(f"{label}:")
    price_text = format_price_for_ticker(value, ticker) if ticker else format_krw(value)
    lines.append(bold(price_text))
    lines.append("")


def append_target_price_analysis(
    lines: list[str],
    analysis: StockAnalysis,
    target_analysis: TargetPriceAnalysis | None = None,
) -> None:
    target_analysis = target_analysis or analysis.target_analysis
    if not target_analysis.levels:
        append_price_block(lines, "목표가", analysis.target_price, analysis.ticker)
        return

    lines.extend(section("🎯 목표가 분석"))
    for level in target_analysis.levels:
        price_text = format_price_for_ticker(level.price, analysis.ticker)
        lines.append(f"{level.label}: {bold(price_text)} {level.emoji}")
    lines.append("")
    lines.append("가장 현실적인 목표:")
    lines.append(bold(target_analysis.most_realistic_label))
    lines.append("")
    lines.append("확장 목표:")
    lines.append(target_analysis.extension_note)
    lines.append("")


def append_risk_block(lines: list[str], action: str, market_state: str) -> None:
    lines.append("리스크:")
    lines.append("* 손절가 이탈 시 추세 훼손")
    if market_state == "하락장":
        lines.append("* 하락장에서는 현금 비중 50% 이상 유지")
    else:
        lines.append("* 시장 변동성 확대 시 비중 축소 검토")
    lines.append("")


def build_context(logger: Logger = None) -> AnalysisContext:
    storage.prune_watchlist_holdings_overlap(logger=logger)
    watchlist_items = storage.load_watchlist(logger=logger)
    holdings = storage.load_holdings(logger=logger)
    news_summary = storage.load_news_summary(logger=logger)
    theme_config = storage.load_theme_config(logger=logger)
    market = analyze_market()
    strong_themes, theme_note = extract_themes_from_news(news_summary)
    return AnalysisContext(
        market=market,
        strong_themes=strong_themes,
        theme_note=theme_note,
        watchlist_items=watchlist_items,
        holdings=holdings,
        news_summary=news_summary,
        theme_config=theme_config,
    )


def analyze_watchlist(context: AnalysisContext) -> list[StockAnalysis]:
    holding_keys: set[str] = set()
    for holding in context.holdings:
        holding_keys.update(storage.item_keys(holding))
    candidates = [
        stock for stock in context.watchlist_items
        if not (storage.item_keys(stock) & holding_keys)
    ]
    return [analyze_stock(stock, context.strong_themes, context.market.state) for stock in candidates]


def analyze_holdings(context: AnalysisContext) -> dict[str, StockAnalysis]:
    return {
        holding["ticker"]: analyze_stock(holding, context.strong_themes, context.market.state)
        for holding in context.holdings
    }


def build_daily_report_messages(
    market: MarketSummary,
    strong_themes: list[str],
    watchlist: list[StockAnalysis],
    holdings: list[dict[str, Any]],
    holding_analyses: dict[str, StockAnalysis],
) -> list[str]:
    now = datetime.now(KST)
    recommendation_pool = [item for item in watchlist if not item.error]
    recommendations = sorted(
        recommendation_pool,
        key=lambda item: (item.composite_score, item.timing_score, item.quant_score),
        reverse=True,
    )[:3]
    new_entry_action = "관망"
    if recommendations and recommendations[0].final_action in {"매수가능", "분할매수", "선별매수", "소액분할매수"}:
        new_entry_action = recommendations[0].final_action
    holding_summary_action = summarize_holding_action(holdings, holding_analyses, market.state)

    message1: list[str] = []
    message1.append("📊 **주식관리 리포트**")
    sent_at_text = f"{now:%Y-%m-%d %H:%M} KST"
    message1.append(f"발송일: {bold(sent_at_text)}")
    message1.append("")
    message1.extend(section("🌎 시장 상태"))
    message1.append(f"시장 상태: {bold(market.state)}")
    message1.append(f"현금 비중 권고: {bold(market.cash_recommendation)}")
    message1.append("")
    message1.extend(section("⚡ 오늘 액션 요약"))
    message1.append(f"* 신규진입: {bold(new_entry_action)}")
    message1.append(f"* 보유종목: {bold(holding_summary_action)}")
    message1.append(f"* 매매원칙: {bold('추격매수 금지')}")
    message1.append("")
    message1.extend(section("🔥 오늘 강한 테마"))
    for index, theme in enumerate(strong_themes[:3], start=1):
        message1.append(f"{index}. {bold(theme)}")
    message1.append("")
    message1.extend(section("🏆 추천 종목 TOP3"))
    if recommendations:
        for item in recommendations:
            message1.append(f"종목명: {bold(item.name)}")
            message1.append(f"퀀트 점수: {bold(item.quant_score)}")
            message1.append(f"매매 타이밍 점수: {bold(item.timing_score)}")
            message1.append(f"액션: {bold(item.final_action)}")
            message1.append("")
            message1.append("진입 가능 구간:")
            message1.append(item.entry_zone)
            message1.append("")
            append_price_block(message1, "손절가", item.stop_price)
            append_target_price_analysis(message1, item)
            message1.append("근거:")
            message1.append("")
            for reason in item.reason_bullets:
                message1.append(f"* {reason}")
            message1.append("")
    else:
        message1.append("추천 가능 종목 없음")
        message1.append("")

    message1.extend(section("👀 관심종목 점검"))
    for item in watchlist:
        message1.append(f"종목명: {bold(item.name)}")
        message1.append(f"상태: {bold(item.current_state)}")
        message1.append(f"액션: {bold(item.final_action)}")
        if item.error:
            message1.append(f"오류: {item.error}")
        message1.append("")

    message2: list[str] = []
    message2.append("💼 **보유종목 관리**")
    message2.append("")
    message2.extend(section("💼 보유종목 관리"))
    if not holdings:
        message2.append("보유종목 없음")
        message2.append("")

    for holding in holdings:
        ticker = holding["ticker"]
        analysis = holding_analyses[ticker]
        quantity = int(holding["quantity"])
        average_price = holding_average_price(holding)
        action, stop_price, target_price = holding_action(analysis, quantity, average_price, market.state)
        profit_pct = None
        if analysis.current_price:
            profit_pct = ((analysis.current_price / average_price) - 1) * 100

        message2.append(f"종목명: {bold(holding['name'])}")
        quantity_text = f"{quantity:,}주"
        message2.append(f"보유수량: {bold(quantity_text)}")
        message2.append(f"평단: {bold(format_price_for_ticker(average_price, ticker))}")
        message2.append(f"현재가: {bold(format_price_for_ticker(analysis.current_price, ticker))}")
        message2.append(f"수익률: {bold(format_pct(profit_pct))}")
        message2.append(f"액션: {bold(action)}")
        message2.append("")
        holding_target_analysis = position_target_price_analysis(analysis, average_price, target_price)
        append_target_price_analysis(message2, analysis, holding_target_analysis)
        append_price_block(message2, "손절가", stop_price, ticker)
        append_risk_block(message2, action, market.state)
        if analysis.error:
            message2.append(f"오류: {analysis.error}")
            message2.append("")

    message2.extend(section("⚠️ 리스크 경고"))
    message2.append("* 추격매수 금지")
    message2.append("* 손절가 이탈 종목 물타기 금지")
    message2.append("* 시장 변동성 확대 시 비중 축소 검토")

    return ["\n".join(message1).strip(), "\n".join(message2).strip()]


def build_daily_reports(logger: Logger = None) -> list[str]:
    log(logger, "리포트 생성 시작")
    context = build_context(logger=logger)
    log(logger, f"시장 상태 판단 완료: {context.market.state}")
    log(logger, f"강한 테마 선정 완료: {', '.join(context.strong_themes[:3])}")
    watchlist = analyze_watchlist(context)
    watchlist_errors = [item for item in watchlist if item.error]
    log(logger, f"관심종목 분석 완료: 성공 {len(watchlist) - len(watchlist_errors)}개, 오류 {len(watchlist_errors)}개")
    holding_analyses = analyze_holdings(context)
    holding_errors = [item for item in holding_analyses.values() if item.error]
    log(logger, f"보유종목 분석 완료: 성공 {len(holding_analyses) - len(holding_errors)}개, 오류 {len(holding_errors)}개")
    reports = build_daily_report_messages(
        market=context.market,
        strong_themes=context.strong_themes,
        watchlist=watchlist,
        holdings=context.holdings,
        holding_analyses=holding_analyses,
    )
    log(logger, f"리포트 생성 완료: 메시지1 {len(reports[0])}자, 메시지2 {len(reports[1])}자")
    return reports


def find_known_stock(query: str, context: AnalysisContext | None = None) -> dict[str, Any] | None:
    context = context or build_context()
    found = storage.find_item(context.watchlist_items, query)
    if found:
        return found
    return storage.find_item(context.holdings, query)


def analyze_query_stock(query: str) -> tuple[StockAnalysis, AnalysisContext]:
    context = build_context()
    resolution = resolve_ticker(query)
    if resolution:
        known_stock = find_known_stock(query, context) or find_known_stock(resolution.ticker, context)
        stock: dict[str, Any] = {"name": resolution.name, "ticker": resolution.ticker}
        if known_stock:
            stock.update(known_stock)
        theme_payload, _ = storage.find_theme_mapping(query, resolution.ticker)
        if theme_payload:
            stock["themes"] = theme_payload.get("themes", [])
            stock["subthemes"] = theme_payload.get("subthemes", [])
        elif not stock.get("themes"):
            stock["themes"] = ["미분류"]
        return analyze_stock(stock, context.strong_themes, context.market.state), context

    known_stock = find_known_stock(query, context)
    if known_stock:
        return analyze_stock(known_stock, context.strong_themes, context.market.state), context

    stock = {"name": query, "ticker": normalize_ticker_symbol(query)}
    return analyze_stock(stock, context.strong_themes, context.market.state), context


def related_news_lines(stock: StockAnalysis, context: AnalysisContext) -> list[str]:
    lines: list[str] = []
    key_news = context.news_summary.get("key_news", [])
    stock_tokens = [stock.name, stock.ticker, *stock.themes]
    normalized_tokens = [normalize_text(token) for token in stock_tokens if token]
    for item in key_news:
        if isinstance(item, dict):
            text = " ".join(str(item.get(key, "")) for key in ("title", "summary", "content"))
            title = str(item.get("title") or item.get("summary") or text)
        else:
            text = str(item)
            title = text
        normalized_text = normalize_text(text)
        if any(token and token in normalized_text for token in normalized_tokens):
            lines.append(title[:80])
    if not lines:
        lines.append(context.theme_note)
    return lines[:3]


def stock_detail_report(query: str) -> str:
    analysis, context = analyze_query_stock(query)
    if analysis.error:
        return (
            "━━━━━━━━━━\n"
            "**🔎 종목분석**\n"
            "━━━━━━━━━━\n\n"
            f"입력값: {bold(query)}\n"
            "상태: **자동검색 실패**\n\n"
            "안내:\n"
            "1. 한국 종목이면 정확한 종목명을 입력해주세요.\n"
            "2. 미국 종목이면 티커로 입력해주세요. 예: NVDA, CRCL\n"
            "3. 그래도 안 되면 /관심추가직접을 사용해주세요."
        )

    lines: list[str] = []
    lines.extend(section("🔎 종목분석"))
    lines.append(f"종목명: {bold(analysis.name)}")
    lines.append(f"티커: {bold(analysis.ticker)}")
    lines.append(f"현재가: {bold(format_price_for_ticker(analysis.current_price, analysis.ticker))}")
    lines.append(f"등락률: {bold(format_pct(analysis.change_pct))}")
    lines.append(f"20일선 위치: {bold(format_pct(analysis.metrics.get('price_vs_ma20')))}")
    lines.append(f"60일선: {bold(format_price_for_ticker(analysis.metrics.get('ma60'), analysis.ticker))}")
    rsi_text = f"{analysis.metrics.get('rsi', 0):.1f}" if not analysis.error else "-"
    volume_text = f"{analysis.metrics.get('volume_ratio', 0):.1f}배" if not analysis.error else "-"
    lines.append(f"RSI: {bold(rsi_text)}")
    lines.append(f"거래량 변화: {bold(volume_text)}")
    lines.append(f"퀀트 점수: {bold(analysis.quant_score)}")
    lines.append(f"매매 타이밍 점수: {bold(analysis.timing_score)}")
    lines.append(f"관련 테마: {bold(', '.join(analysis.themes) if analysis.themes else '-')}")
    lines.append("")
    lines.append("뉴스봇 연동:")
    for news in related_news_lines(analysis, context):
        lines.append(f"* {news}")
    lines.append("")
    lines.append("진입 가능 구간:")
    lines.append(analysis.entry_zone)
    lines.append("")
    append_price_block(lines, "손절가", analysis.stop_price, analysis.ticker)
    append_target_price_analysis(lines, analysis)
    lines.append(f"최종 액션: {bold(analysis.final_action)}")
    lines.append("")
    lines.append("근거:")
    for reason in analysis.reason_bullets[:3]:
        lines.append(f"* {reason}")
    lines.append("")
    lines.append("리스크:")
    for risk in analysis.risk_bullets[:3]:
        lines.append(f"* {risk}")
    return "\n".join(lines).strip()


def strong_theme_stock_names() -> str:
    context = build_context()
    strong_priority_themes = [
        theme for theme in context.strong_themes
        if is_priority_theme(theme, context.theme_config)
    ]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    holding_keys: set[str] = set()
    for holding in context.holdings:
        holding_keys.update(storage.item_keys(holding))

    for stock in context.watchlist_items:
        if storage.item_keys(stock) & holding_keys:
            continue
        if strong_priority_themes and not any(stock_matches_theme(stock, theme, context.theme_config) for theme in strong_priority_themes):
            continue
        ticker = str(stock.get("ticker", ""))
        if ticker and ticker not in seen:
            candidates.append(stock)
            seen.add(ticker)

    for stock in theme_representatives(context.theme_config, strong_priority_themes):
        if storage.item_keys(stock) & holding_keys:
            continue
        ticker = str(stock.get("ticker", ""))
        if ticker and ticker not in seen:
            candidates.append(stock)
            seen.add(ticker)

    analyses = [analyze_stock(stock, context.strong_themes, context.market.state) for stock in candidates]
    ranked = sorted(
        [item for item in analyses if not item.error],
        key=lambda item: (item.composite_score, item.timing_score, item.quant_score),
        reverse=True,
    )[:3]
    lines = ["오늘 강한 테마 추천종목:", ""]
    for index, item in enumerate(ranked, start=1):
        lines.append(f"{index}. {item.name}")
    if not ranked:
        lines.append("추천 가능 종목 없음")
    return "\n".join(lines)


def watchlist_text() -> str:
    storage.prune_watchlist_holdings_overlap()
    items = storage.load_watchlist()
    theme_config = storage.load_theme_config()
    lines = section("⭐ 관심종목 목록")
    if not items:
        lines.append("관심종목 없음")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        themes, _, non_priority = normalize_stock_theme_fields(item, theme_config)
        group_themes = themes or ["미분류"]
        for theme in group_themes:
            grouped.setdefault(theme, []).append(item)
        for theme in non_priority:
            grouped.setdefault(f"{theme} (비우선 테마)", []).append(item)

    priority_order = priority_theme_names(theme_config)
    ordered_themes = [theme for theme in priority_order if theme in grouped]
    ordered_themes.extend(theme for theme in grouped if theme not in ordered_themes)

    for theme in ordered_themes:
        lines.append(f"**{theme}**")
        lines.append("")
        seen: set[str] = set()
        for item in grouped[theme]:
            ticker = str(item.get("ticker", "-"))
            if ticker in seen:
                continue
            seen.add(ticker)
            lines.append(f"* {item.get('name', '-')} / {ticker}")
        lines.append("")
    return "\n".join(lines).strip()


def holdings_text() -> str:
    storage.prune_watchlist_holdings_overlap()
    items = storage.load_holdings()
    lines = section("💼 보유목록")
    if not items:
        lines.append("보유종목 없음")
    for item in items:
        lines.append(f"종목명: {bold(item.get('name', '-'))}")
        lines.append(f"티커: {bold(item.get('ticker', '-'))}")
        quantity_text = f"{int(item.get('quantity', 0)):,}주"
        lines.append(f"보유수량: {bold(quantity_text)}")
        lines.append(f"평단: {bold(format_price_for_ticker(holding_average_price(item), str(item.get('ticker', ''))))}")
        lines.append("")
    return "\n".join(lines).strip()


def portfolio_check_report() -> str:
    context = build_context()
    holding_analyses = analyze_holdings(context)
    total_value = 0.0
    rows: list[tuple[dict[str, Any], StockAnalysis, float, float | None]] = []
    theme_values: dict[str, float] = {}
    for holding in context.holdings:
        analysis = holding_analyses[holding["ticker"]]
        quantity = int(holding["quantity"])
        value = (analysis.current_price or 0) * quantity
        total_value += value
        profit_pct = None
        if analysis.current_price:
            profit_pct = ((analysis.current_price / holding_average_price(holding)) - 1) * 100
        rows.append((holding, analysis, value, profit_pct))
        themes, _, _ = normalize_stock_theme_fields(holding, context.theme_config)
        for theme in themes or ["미분류"]:
            theme_values[theme] = theme_values.get(theme, 0.0) + value

    lines = section("📦 포트폴리오점검")
    if not rows:
        lines.append("보유종목 없음")
        return "\n".join(lines).strip()

    for holding, analysis, value, profit_pct in rows:
        weight = (value / total_value * 100) if total_value else 0
        action, _, _ = holding_action(analysis, int(holding["quantity"]), holding_average_price(holding), context.market.state)
        lines.append(f"종목명: {bold(holding['name'])}")
        lines.append(f"평가금액: {bold(format_krw(value))}")
        lines.append(f"수익률: {bold(format_pct(profit_pct))}")
        weight_text = f"{weight:.1f}%"
        lines.append(f"비중: {bold(weight_text)}")
        lines.append(f"액션: {bold(action)}")
        lines.append("")

    lines.append("테마별 비중:")
    if theme_values and total_value:
        for theme, value in sorted(theme_values.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"* {theme}: {value / total_value * 100:.1f}%")
    else:
        lines.append("* 미분류")
    lines.append("")

    top_theme, top_value = max(theme_values.items(), key=lambda item: item[1]) if theme_values else ("분산", 0.0)
    top_weight = top_value / total_value * 100 if total_value else 0.0
    missing_core = [
        theme for theme in priority_theme_names(context.theme_config)
        if theme not in theme_values
    ][:3]
    lines.append("리스크 요약:")
    if top_weight >= 50:
        lines.append(f"* {top_theme} 비중 과다: {top_weight:.1f}%")
    else:
        lines.append(f"* 최대 노출 테마: {top_theme} {top_weight:.1f}%")
    if missing_core:
        lines.append(f"* 노출 없음: {', '.join(missing_core)}")
    lines.append(f"* 현금 비중 제안: {context.market.cash_recommendation}")
    lines.append(f"* 시장 상태: {context.market.state}")
    return "\n".join(lines).strip()


def market_status_report() -> str:
    market = analyze_market()
    strength = {
        "상승장": "강",
        "변동성 확대장": "중",
        "횡보장": "약",
        "하락장": "매우 약",
    }.get(market.state, "약")
    lines = section("🌎 시장상태")
    lines.append(f"시장 상태: {bold(market.state)}")
    lines.append(f"현금 비중 권고: {bold(market.cash_recommendation)}")
    lines.append(f"신규매수 강도: {bold(strength)}")
    lines.append("")
    lines.append("근거:")
    for reason in market.reasons[:3]:
        lines.append(f"* {reason}")
    return "\n".join(lines).strip()


def today_strategy_report() -> str:
    context = build_context()
    lines = section("⚡ 오늘전략")
    can_buy = "가능" if context.market.state == "상승장" else "선별" if context.market.state == "변동성 확대장" else "관망"
    lines.append(f"신규매수: {bold(can_buy)}")
    wait_policy = "필수" if context.market.state in {"하락장", "횡보장"} else "부분 관망"
    lines.append(f"관망 여부: {bold(wait_policy)}")
    lines.append(f"추격매수 금지: {bold('예')}")
    lines.append(f"현금 비중 전략: {bold(context.market.cash_recommendation)}")
    return "\n".join(lines).strip()


def strong_themes_report() -> str:
    news = storage.load_news_summary()
    themes, note = extract_themes_from_news(news)
    lines = section("🔥 강한테마")
    for index, theme in enumerate(themes[:3], start=1):
        lines.append(f"{index}. {bold(theme)}")
    lines.append("")
    lines.append(f"기준: {note}")
    return "\n".join(lines).strip()


def stuck_report(query: str, average_price: float) -> str:
    analysis, context = analyze_query_stock(query)
    profit_pct = None
    if analysis.current_price:
        profit_pct = ((analysis.current_price / float(average_price)) - 1) * 100
    time_stop = "5거래일 내 20일선 회복 실패 시 비중 축소"
    hold_zone = f"{format_krw(analysis.stop_price)} ~ {format_krw(average_price)}"
    action = "손절주의" if profit_pct is not None and profit_pct <= -8 else "관망"
    lines = section("🧯 물림 분석")
    lines.append(f"종목명: {bold(analysis.name)}")
    lines.append(f"평단: {bold(format_krw(average_price))}")
    lines.append(f"현재가: {bold(format_krw(analysis.current_price))}")
    lines.append(f"손익률: {bold(format_pct(profit_pct))}")
    append_price_block(lines, "기술적 손절가", analysis.stop_price)
    lines.append("버틸 구간:")
    lines.append(hold_zone)
    lines.append("")
    lines.append(f"시간손절 기준: {bold(time_stop)}")
    lines.append(f"대응 액션: {bold(action)}")
    _ = context
    return "\n".join(lines).strip()


def theme_check_report(theme: str) -> str:
    context = build_context()
    watchlist = analyze_watchlist(context)
    related = [
        item for item in watchlist
        if stock_matches_theme(item, theme, context.theme_config)
        or normalize_text(theme) in normalize_text(item.name)
    ]
    theme_is_strong = any(normalize_text(theme) in normalize_text(strong) or normalize_text(strong) in normalize_text(theme) for strong in context.strong_themes)
    avg_rsi = np.mean([item.metrics.get("rsi", 50) for item in related]) if related else 50
    lines = section("🧭 테마점검")
    lines.append(f"테마명: {bold(theme)}")
    lines.append(f"지속성: {bold('높음' if theme_is_strong else '보통')}")
    lines.append(f"과열도: {bold('높음' if avg_rsi >= 70 else '보통')}")
    lines.append("")
    lines.append("관련 종목:")
    if related:
        for item in related[:5]:
            lines.append(f"* {item.name}")
    else:
        lines.append("* 관심종목 내 관련 종목 없음")
    lines.append("")
    lines.append("리스크:")
    lines.append("* 뉴스 모멘텀 약화 시 순환매 가능")
    lines.append("* 거래량 과열 구간 추격매수 금지")
    return "\n".join(lines).strip()


def build_deep_analysis_candidates(max_count: int | None = None) -> list[dict[str, Any]]:
    context = build_context()
    limit = max_count or int(context.theme_config.get("max_deep_analysis_candidates", 50) or 50)
    strong_priority_themes = [
        theme for theme in context.strong_themes
        if is_priority_theme(theme, context.theme_config)
    ]
    pools = [
        context.holdings,
        context.watchlist_items,
        theme_representatives(context.theme_config),
        theme_representatives(context.theme_config, strong_priority_themes),
    ]

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pool in pools:
        for item in pool:
            ticker = str(item.get("ticker", ""))
            if not ticker or ticker in seen:
                continue
            candidates.append(item)
            seen.add(ticker)
            if len(candidates) >= limit:
                return candidates
    return candidates
