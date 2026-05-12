from __future__ import annotations

from typing import Any

import analyzer
import storage


Logger = analyzer.Logger

MARKET_GROUP_ORDER = ["KOSPI", "KOSDAQ", "NASDAQ", "기타"]
MARKET_GROUP_LABELS = {
    "KOSPI": "🟦 **KOSPI**",
    "KOSDAQ": "🟨 **KOSDAQ**",
    "NASDAQ": "🟩 **NASDAQ**",
    "기타": "**기타**",
}
THEME_REFRESH_TARGETS = {"AAOI", "COHR"}


def display_ticker_code(ticker: str | None) -> str:
    normalized = str(ticker or "").strip().upper()
    if normalized.endswith((".KS", ".KQ")):
        return normalized[:-3]
    return normalized


def display_stock_name(item: dict[str, Any]) -> str:
    name = str(item.get("name", "-") or "-")
    code = display_ticker_code(str(item.get("ticker", "")))
    return f"{name} ({code})" if code else name


def resolve_market_group(ticker: str | None) -> str:
    normalized = str(ticker or "").strip().upper()
    if normalized.endswith(".KS"):
        return "KOSPI"
    if normalized.endswith(".KQ"):
        return "KOSDAQ"
    if analyzer.looks_like_us_ticker(normalized):
        return "NASDAQ"
    return "기타"


def grouped_by_market(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        market = resolve_market_group(str(item.get("ticker", "")))
        grouped.setdefault(market, []).append(item)

    ordered_markets = [market for market in MARKET_GROUP_ORDER if market in grouped]
    ordered_markets.extend(market for market in grouped if market not in ordered_markets)
    return [(market, grouped[market]) for market in ordered_markets]


def append_market_group_header(lines: list[str], market: str) -> None:
    lines.append(MARKET_GROUP_LABELS.get(market, MARKET_GROUP_LABELS["기타"]))
    lines.append("━━━━━━━━━━")


def theme_values_are_unclassified(value: Any) -> bool:
    if value is None:
        return True
    values = value if isinstance(value, list) else [value]
    labels = [str(item).strip() for item in values if str(item).strip()]
    return not labels or all(storage.normalize(label) == storage.normalize("미분류") for label in labels)


def theme_payload_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def refresh_watchlist_target_themes() -> int:
    items = storage.load_watchlist()
    if not items:
        return 0

    theme_map = storage.load_theme_map()
    updated = 0
    for item in items:
        ticker = str(item.get("ticker", "")).strip().upper()
        name = str(item.get("name", "")).strip().upper()
        target = ticker if ticker in THEME_REFRESH_TARGETS else name if name in THEME_REFRESH_TARGETS else ""
        if not target or not theme_values_are_unclassified(item.get("themes")):
            continue

        payload = theme_map.get(target)
        if not isinstance(payload, dict):
            continue

        themes = theme_payload_values(payload.get("themes"))
        if not themes:
            continue

        item["themes"] = themes
        subthemes = theme_payload_values(payload.get("subthemes"))
        if subthemes:
            item["subthemes"] = subthemes
        updated += 1

    if updated:
        storage.save_watchlist(items)
    return updated


def watchlist_text() -> str:
    storage.prune_watchlist_holdings_overlap()
    refresh_watchlist_target_themes()
    items = storage.load_watchlist()
    theme_config = storage.load_theme_config()
    lines = analyzer.section("⭐ 관심종목 목록")
    if not items:
        lines.append("관심종목 없음")
        return "\n".join(lines).strip()

    for market, market_items in grouped_by_market(items):
        append_market_group_header(lines, market)
        seen: set[str] = set()
        for item in market_items:
            ticker = str(item.get("ticker", ""))
            if ticker in seen:
                continue
            seen.add(ticker)
            themes = analyzer.stock_theme_labels(item, theme_config)
            theme_text = ", ".join(themes) if themes else "미분류"
            lines.append(f"종목명: {analyzer.bold(display_stock_name(item))}")
            lines.append(f"테마: {analyzer.bold(theme_text)}")
            lines.append("")
    return "\n".join(lines).strip()


def holdings_text(items: list[dict[str, Any]] | None = None, logger: Logger = None) -> str:
    if items is None:
        storage.prune_watchlist_holdings_overlap(logger=logger)
        items = storage.load_holdings(logger=logger)

    analyzer.log(
        logger,
        f"보유목록 출력 준비: holdings {len(items)}개 / 저장소: {storage.storage_location_text(storage.HOLDINGS_FILE)}",
    )
    realized_totals = analyzer.realized_profit_map(storage.load_trade_history(logger=logger))
    lines = analyzer.section("💼 보유목록")
    if not items:
        lines.append("보유종목 없음")
        return "\n".join(lines).strip()

    for market, market_items in grouped_by_market(items):
        append_market_group_header(lines, market)
        for item in market_items:
            ticker = str(item.get("ticker", ""))
            quantity = int(item.get("quantity", 0))
            average_price = analyzer.holding_average_price(item)
            analysis = analyzer.analyze_stock(item, [], "횡보장")
            current_price = analysis.current_price
            valuation_profit = None
            valuation_return_pct = None
            if current_price and average_price:
                valuation_profit = (current_price - average_price) * quantity
                valuation_return_pct = ((current_price / average_price) - 1) * 100

            lines.append(f"종목명: {analyzer.bold(display_stock_name(item))}")
            lines.append(f"보유수량: {analyzer.bold(f'{quantity:,}주')}")
            lines.append(f"평단: {analyzer.bold(analyzer.format_price_for_ticker(average_price, ticker))}")
            lines.append(f"현재가: {analyzer.bold(analyzer.format_price_for_ticker(current_price, ticker))}")
            valuation_text = (
                f"{analyzer.format_signed_price_for_ticker(valuation_profit, ticker)} / "
                f"{analyzer.format_pct(valuation_return_pct)}"
            )
            lines.append(f"평가손익: {analyzer.bold(valuation_text)}")
            realized_text = analyzer.format_signed_price_for_ticker(realized_totals.get(ticker, 0.0), ticker)
            lines.append(f"실현손익 누적: {analyzer.bold(realized_text)}")
            if hasattr(analyzer, "holding_action"):
                action, _, _ = analyzer.holding_action(analysis, quantity, average_price, "횡보장")
                lines.append(f"액션: {analyzer.bold(action)}")
            if analysis.error:
                lines.append(f"시세 오류: {analysis.error}")
            lines.append("")
    return "\n".join(lines).strip()
