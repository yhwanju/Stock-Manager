from __future__ import annotations

from typing import Any, Callable

import analyzer
import storage


THEME_UNIVERSE_FILE = "theme_universe.json"
DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT = 100
MAX_RECOMMENDATION_CANDIDATE_LIMIT = 120

Logger = Callable[[str], None] | None

_PATCHED = False
_ORIGINAL_EXTRACT_PRIORITY: Callable[..., list[str]] | None = None
_ORIGINAL_EXTRACT_THEMES: Callable[[dict[str, Any]], tuple[list[str], str]] | None = None
_ORIGINAL_ANALYZE_WATCHLIST: Callable[[Any], list[Any]] | None = None
_ORIGINAL_SELECT_TOP: Callable[[list[Any]], list[Any]] | None = None
_ORIGINAL_DEEP_CANDIDATES: Callable[..., list[dict[str, Any]]] | None = None
_ORIGINAL_CONDITION_CANDIDATES: Callable[..., list[dict[str, Any]]] | None = None
_ORIGINAL_STRONG_THEME_NAMES: Callable[[], str] | None = None
_LAST_RECOMMENDATION_CANDIDATES: list[Any] = []


def _emit_log(logger: Logger, message: str) -> None:
    if logger:
        logger(message)
    else:
        print(message, flush=True)


def recommendation_candidate_limit(theme_config: dict[str, Any] | None = None, default: int = DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT) -> int:
    config = theme_config or {}
    try:
        limit = int(config.get("max_recommendation_candidates", default))
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, MAX_RECOMMENDATION_CANDIDATE_LIMIT))


def load_theme_universe(logger: Logger = None) -> dict[str, list[str]]:
    payload = storage.load_json_file(THEME_UNIVERSE_FILE, {}, logger=logger)
    if not isinstance(payload, dict):
        _emit_log(logger, f"{THEME_UNIVERSE_FILE} 로드 실패: 객체 형식이 아닙니다.")
        return {}

    universe: dict[str, list[str]] = {}
    for theme, tickers in payload.items():
        if not isinstance(tickers, list):
            continue
        cleaned = [analyzer.normalize_ticker_symbol(str(ticker)) for ticker in tickers if str(ticker).strip()]
        if cleaned:
            universe[str(theme)] = cleaned
    return universe


def allowed_theme_names(theme_config: dict[str, Any]) -> list[str]:
    allowed = analyzer.priority_theme_names(theme_config)
    for theme in load_theme_universe():
        if theme not in allowed:
            allowed.append(theme)
    return allowed


def resolve_allowed_theme(raw_theme: Any, theme_config: dict[str, Any], allowed_themes: list[str]) -> str:
    if not raw_theme:
        return ""
    candidates = [analyzer.canonical_theme(str(raw_theme), theme_config), str(raw_theme).strip()]
    for candidate in candidates:
        normalized = analyzer.normalize_text(candidate)
        for theme in allowed_themes:
            if analyzer.normalize_text(theme) == normalized:
                return theme
    return ""


def extract_priority_theme_payload(news_summary: dict[str, Any], theme_config: dict[str, Any] | None = None) -> list[str]:
    config = theme_config or storage.load_theme_config()
    allowed = allowed_theme_names(config)
    themes: list[str] = []

    def add_theme(raw_theme: Any) -> None:
        selected = resolve_allowed_theme(raw_theme, config, allowed)
        if selected and selected not in themes:
            themes.append(selected)

    raw_themes = news_summary.get("themes", [])
    if isinstance(raw_themes, list):
        for item in raw_themes:
            add_theme(item.get("name") or item.get("theme") if isinstance(item, dict) else item)

    raw_news = news_summary.get("key_news", [])
    if isinstance(raw_news, list):
        for item in raw_news:
            if not isinstance(item, dict):
                continue
            item_themes = item.get("themes", [])
            if isinstance(item_themes, list):
                for theme in item_themes:
                    add_theme(theme)

    return themes


def extract_themes_from_news(news_summary: dict[str, Any]) -> tuple[list[str], str]:
    themes: list[str] = []
    note = "뉴스 요약 파일을 반영했습니다."
    if _ORIGINAL_EXTRACT_THEMES is not None:
        themes, note = _ORIGINAL_EXTRACT_THEMES(news_summary)

    extras = extract_priority_theme_payload(news_summary)
    merged = [theme for theme in extras if theme not in themes]
    merged.extend(theme for theme in themes if theme not in merged)
    return merged[:3], note


def _theme_matches(strong_theme: str, universe_theme: str, theme_config: dict[str, Any]) -> bool:
    strong = analyzer.normalize_text(strong_theme)
    universe = analyzer.normalize_text(universe_theme)
    if strong == universe:
        return True
    if strong and universe and (strong in universe or universe in strong):
        return True
    return analyzer.normalize_text(analyzer.canonical_theme(strong_theme, theme_config)) == analyzer.normalize_text(
        analyzer.canonical_theme(universe_theme, theme_config)
    )


def _stock_name_from_ticker(ticker: str, ticker_map: dict[str, str]) -> str:
    normalized_ticker = storage.normalize(ticker)
    for name, mapped_ticker in ticker_map.items():
        if storage.normalize(str(mapped_ticker)) == normalized_ticker:
            return str(name)
    return ticker


def _theme_universe_stock_item(ticker: str, universe_theme: str, theme_map: dict[str, dict[str, Any]], ticker_map: dict[str, str]) -> dict[str, Any]:
    normalized_ticker = analyzer.normalize_ticker_symbol(ticker)
    name = _stock_name_from_ticker(normalized_ticker, ticker_map)
    payload, mapped_name = storage.find_theme_mapping(normalized_ticker, normalized_ticker, theme_map=theme_map, ticker_map=ticker_map)

    themes: list[str] = []
    subthemes: list[str] = []
    if isinstance(payload, dict):
        themes = analyzer.split_theme_values(payload.get("themes"))
        subthemes = analyzer.split_theme_values(payload.get("subthemes"))
        if mapped_name and name == normalized_ticker:
            name = mapped_name

    if universe_theme not in themes:
        themes.append(universe_theme)
    if universe_theme not in subthemes:
        subthemes.append(universe_theme)

    return {
        "name": name,
        "ticker": normalized_ticker,
        "themes": themes,
        "subthemes": subthemes,
        "source": f"theme_universe:{universe_theme}",
    }


def theme_universe_candidate_items(strong_themes: list[str], theme_config: dict[str, Any], logger: Logger = None) -> list[dict[str, Any]]:
    universe = load_theme_universe(logger=logger)
    if not universe or not strong_themes:
        return []

    theme_map = storage.load_theme_map(logger=logger)
    ticker_map = storage.load_ticker_map(logger=logger)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for universe_theme, tickers in universe.items():
        if not any(_theme_matches(theme, universe_theme, theme_config) for theme in strong_themes):
            continue
        added = 0
        for ticker in tickers:
            normalized_ticker = analyzer.normalize_ticker_symbol(str(ticker))
            key = analyzer.normalize_text(normalized_ticker)
            if not normalized_ticker or key in seen:
                continue
            candidates.append(_theme_universe_stock_item(normalized_ticker, universe_theme, theme_map, ticker_map))
            seen.add(key)
            added += 1
        _emit_log(logger, f"[theme-universe] {universe_theme} 테마에서 {added}개 후보 추가")

    return candidates


def dedupe_candidate_items(pools: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pool in pools:
        for item in pool:
            ticker = analyzer.normalize_ticker_symbol(str(item.get("ticker", "")))
            key = analyzer.normalize_text(ticker)
            if not ticker or key in seen:
                continue
            candidate = dict(item)
            candidate["ticker"] = ticker
            candidates.append(candidate)
            seen.add(key)
            if len(candidates) >= limit:
                return candidates
    return candidates


def build_recommendation_candidate_items(context: Any, logger: Logger = None) -> list[dict[str, Any]]:
    universe_items = theme_universe_candidate_items(context.strong_themes, context.theme_config, logger=logger)
    candidates = dedupe_candidate_items(
        [context.holdings, context.watchlist_items, universe_items],
        recommendation_candidate_limit(context.theme_config),
    )
    _emit_log(
        logger,
        f"[theme-universe] 추천 후보군 구성: 보유 {len(context.holdings)}개, 관심 {len(context.watchlist_items)}개, universe {len(universe_items)}개, 최종 {len(candidates)}개",
    )
    return candidates


def analyze_watchlist_with_theme_universe(context: Any) -> list[Any]:
    global _LAST_RECOMMENDATION_CANDIDATES
    watchlist_analyses = _ORIGINAL_ANALYZE_WATCHLIST(context) if _ORIGINAL_ANALYZE_WATCHLIST else []
    watchlist_by_ticker = {analyzer.normalize_text(str(item.ticker)): item for item in watchlist_analyses}
    recommendation_candidates: list[Any] = []

    for item in build_recommendation_candidate_items(context):
        ticker_key = analyzer.normalize_text(str(item.get("ticker", "")))
        if ticker_key in watchlist_by_ticker:
            recommendation_candidates.append(watchlist_by_ticker[ticker_key])
        else:
            recommendation_candidates.append(analyzer.analyze_stock(item, context.strong_themes, context.market.state))

    _LAST_RECOMMENDATION_CANDIDATES = recommendation_candidates
    return watchlist_analyses


def select_top_recommendations_with_theme_universe(watchlist: list[Any]) -> list[Any]:
    candidates = _LAST_RECOMMENDATION_CANDIDATES or watchlist
    return _ORIGINAL_SELECT_TOP(candidates) if _ORIGINAL_SELECT_TOP else []


def build_deep_analysis_candidates(max_count: int | None = None) -> list[dict[str, Any]]:
    base = _ORIGINAL_DEEP_CANDIDATES(max_count) if _ORIGINAL_DEEP_CANDIDATES else []
    context = analyzer.build_context()
    limit = max_count or int(context.theme_config.get("max_deep_analysis_candidates", 50) or 50)
    universe_items = theme_universe_candidate_items(context.strong_themes, context.theme_config)
    return dedupe_candidate_items([base, universe_items], limit)


def build_condition_search_candidates(context: Any, max_count: int | None = None) -> list[dict[str, Any]]:
    base = _ORIGINAL_CONDITION_CANDIDATES(context, max_count) if _ORIGINAL_CONDITION_CANDIDATES else []
    limit = max_count or int(context.theme_config.get("max_deep_analysis_candidates", 50) or 50)
    universe_items = theme_universe_candidate_items(context.strong_themes, context.theme_config)
    return dedupe_candidate_items([base, universe_items], limit)


def strong_theme_stock_names() -> str:
    if _ORIGINAL_STRONG_THEME_NAMES is None:
        return "추천 가능 종목 없음"

    context = analyzer.build_context()
    candidate_items = build_recommendation_candidate_items(context)
    if not candidate_items:
        return _ORIGINAL_STRONG_THEME_NAMES()

    analyses = [analyzer.analyze_stock(stock, context.strong_themes, context.market.state) for stock in candidate_items]
    ranked = sorted(
        [item for item in analyses if not item.error],
        key=lambda item: (item.composite_score, item.timing_score, item.quant_score),
        reverse=True,
    )[:3]
    lines = ["뉴스 기반 강한테마 추천종목:", ""]
    for index, item in enumerate(ranked, start=1):
        lines.append(f"{index}. {item.name}")
    if not ranked:
        lines.append("추천 가능 종목 없음")
    lines.extend(
        [
            "",
            "기준:",
            analyzer.bold("뉴스 연동 기반 → 보유/관심/theme_universe 후보 점수 기준"),
            "",
            "데이터 출처:",
            f"* {analyzer.bold('보유종목 기반')}",
            f"* {analyzer.bold('관심종목 기반')}",
            f"* {analyzer.bold('theme_universe 기반')}",
        ]
    )
    return "\n".join(lines)


def patch_analyzer_theme_universe() -> None:
    global _PATCHED
    global _ORIGINAL_ANALYZE_WATCHLIST
    global _ORIGINAL_CONDITION_CANDIDATES
    global _ORIGINAL_DEEP_CANDIDATES
    global _ORIGINAL_EXTRACT_PRIORITY
    global _ORIGINAL_EXTRACT_THEMES
    global _ORIGINAL_SELECT_TOP
    global _ORIGINAL_STRONG_THEME_NAMES

    if _PATCHED:
        return

    _ORIGINAL_EXTRACT_PRIORITY = analyzer.extract_priority_theme_payload
    _ORIGINAL_EXTRACT_THEMES = analyzer.extract_themes_from_news
    _ORIGINAL_ANALYZE_WATCHLIST = analyzer.analyze_watchlist
    _ORIGINAL_SELECT_TOP = analyzer.select_top_recommendations
    _ORIGINAL_DEEP_CANDIDATES = analyzer.build_deep_analysis_candidates
    _ORIGINAL_CONDITION_CANDIDATES = analyzer.build_condition_search_candidates
    _ORIGINAL_STRONG_THEME_NAMES = analyzer.strong_theme_stock_names

    analyzer.extract_priority_theme_payload = extract_priority_theme_payload
    analyzer.extract_themes_from_news = extract_themes_from_news
    analyzer.analyze_watchlist = analyze_watchlist_with_theme_universe
    analyzer.select_top_recommendations = select_top_recommendations_with_theme_universe
    analyzer.build_deep_analysis_candidates = build_deep_analysis_candidates
    analyzer.build_condition_search_candidates = build_condition_search_candidates
    analyzer.strong_theme_stock_names = strong_theme_stock_names
    _PATCHED = True
