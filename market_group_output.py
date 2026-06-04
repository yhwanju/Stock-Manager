from __future__ import annotations

from typing import Any

import analyzer
import storage
import theme_universe


theme_universe.patch_analyzer_theme_universe()

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
    theme_universe.sync_theme_universe_cache(force=True)
    storage.auto_patch_themes_from_universe()
    storage.prune_watchlist_holdings_overlap()
    refresh_watchlist_target_themes()
    context = analyzer.build_context()
    items = context.watchlist_items
    theme_config = context.theme_config
    analyses = analyzer.analyze_watchlist(context)
    analysis_by_ticker = {
        analyzer.normalize_text(item.ticker): item
        for item in analyses
    }
    matches = analyzer.match_portfolio_with_strong_themes(context.holdings, items, context.strong_themes, theme_config)
    matched_tickers = {
        analyzer.normalize_text(str(row["item"].get("ticker", "")))
        for row in matches["matched_watchlist"]
    }
    lines = analyzer.section("⭐ 관심종목 목록")
    if not items:
        lines.append("관심종목 없음")
        return "\n".join(lines).strip()

    lines.append("오늘 강한테마 매칭 종목")
    lines.append("━━━━━━━━━━")
    if matches["matched_watchlist"]:
        for row in sorted(matches["matched_watchlist"], key=lambda item: item["match"]["strength_score"], reverse=True):
            item = row["item"]
            match = row["match"]
            analysis = analysis_by_ticker.get(analyzer.normalize_text(str(item.get("ticker", ""))))
            reason = analyzer.action_reason_for_stock(analysis, match, True) if analysis else match["reason"]
            lines.append(f"종목명: {analyzer.bold(display_stock_name(item))}")
            lines.append(f"테마 매칭: {analyzer.bold(match['matched_theme'] + ' ' + match['match_strength'])}")
            if analysis:
                lines.append(f"판단: {analyzer.bold(analysis.final_action)} - {reason}")
                lines.append(f"관찰 가격: {analyzer.bold(analysis.entry_zone)}")
            else:
                lines.append(f"판단 사유: {reason}")
            lines.append("")
    else:
        lines.append("강한테마와 직접 매칭되는 관심종목 없음")
        lines.append("")

    lines.append("눌림 대기 종목")
    lines.append("━━━━━━━━━━")
    pullback_rows: list[tuple[dict[str, Any], Any]] = []
    for item in items:
        ticker_key = analyzer.normalize_text(str(item.get("ticker", "")))
        if ticker_key in matched_tickers:
            continue
        analysis = analysis_by_ticker.get(ticker_key)
        if analysis and not analysis.error and (
            analysis.final_action in {"눌림대기", "관망"}
            or abs(float(analysis.metrics.get("price_vs_ma20", 99.0) or 99.0)) <= 5
        ):
            pullback_rows.append((item, analysis))
    if pullback_rows:
        for item, analysis in sorted(pullback_rows, key=lambda row: row[1].timing_score, reverse=True):
            themes = analyzer.stock_theme_labels(item, theme_config)
            lines.append(f"종목명: {analyzer.bold(display_stock_name(item))}")
            lines.append(f"테마: {analyzer.bold(', '.join(themes) if themes else '미분류')}")
            lines.append(f"판단: {analyzer.bold(analysis.final_action)} - 눌림 확인 후 접근")
            lines.append(f"관찰 가격: {analyzer.bold(analysis.entry_zone)}")
            lines.append("")
    else:
        lines.append("눌림 대기 후보 없음")
        lines.append("")

    lines.append("제외 종목")
    lines.append("━━━━━━━━━━")
    excluded = [
        item for item in items
        if analyzer.normalize_text(str(item.get("ticker", ""))) not in matched_tickers
        and all(item is not row[0] for row in pullback_rows)
    ]
    if excluded:
        for item in excluded:
            ticker_key = analyzer.normalize_text(str(item.get("ticker", "")))
            analysis = analysis_by_ticker.get(ticker_key)
            reason = "시세 오류" if analysis and analysis.error else "오늘 강한테마와 연결성이 낮아 우선순위 제외"
            lines.append(f"* {display_stock_name(item)}: {reason}")
    else:
        lines.append("제외 종목 없음")
    lines.append("")

    lines.append("전체 목록")
    lines.append("━━━━━━━━━━")
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
            action, _stop_price, _target_price = analyzer.holding_action(analysis, quantity, average_price, "횡보장")

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
            lines.append(f"액션: {analyzer.bold(action)}")
            if analysis.error:
                lines.append(f"시세 오류: {analysis.error}")
            lines.append("")
    return "\n".join(lines).strip()
