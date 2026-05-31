from __future__ import annotations

from collections import Counter, defaultdict
import time
from typing import Any, Callable

import analyzer
import google_sheets_store
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
_ORIGINAL_STRONG_THEMES_REPORT: Callable[[], str] | None = None
_ORIGINAL_THEME_CHECK_REPORT: Callable[[str], str] | None = None
_LAST_RECOMMENDATION_CANDIDATES: list[Any] = []
_LAST_RECOMMENDATION_META_BY_TICKER: dict[str, dict[str, Any]] = {}
_LAST_SHEET_SYNC_ATTEMPT = 0.0
SHEET_SYNC_MIN_INTERVAL_SECONDS = 60.0
PRIORITY_WEIGHTS = {"S": 5, "A": 4, "B": 2, "C": 1}
SUPPORTED_MARKETS = ("KOSPI", "KOSDAQ", "NASDAQ", "NYSE")


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


def sync_theme_universe_cache(logger: Logger = None, force: bool = False) -> dict[str, Any]:
    global _LAST_SHEET_SYNC_ATTEMPT
    now = time.monotonic()
    if not force and now - _LAST_SHEET_SYNC_ATTEMPT < SHEET_SYNC_MIN_INTERVAL_SECONDS:
        return google_sheets_store.last_theme_universe_sync_status()
    _LAST_SHEET_SYNC_ATTEMPT = now
    google_sheets_store.sync_theme_universe_from_sheet(logger=logger)
    return google_sheets_store.last_theme_universe_sync_status()


def load_theme_universe(logger: Logger = None) -> dict[str, list[str]]:
    sync_theme_universe_cache(logger=logger)
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


def load_theme_universe_rows(logger: Logger = None) -> list[dict[str, Any]]:
    sync_theme_universe_cache(logger=logger)
    rows = google_sheets_store.theme_universe_rows(logger=logger)
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status", "active")).strip().lower() != "active":
            continue
        ticker = analyzer.normalize_ticker_symbol(str(row.get("ticker", "")))
        if not ticker:
            continue
        item = dict(row)
        item["ticker"] = ticker
        item["name"] = str(item.get("name") or ticker).strip()
        item["market"] = _infer_market(item)
        item["themes"] = analyzer.split_theme_values(item.get("themes"))
        item["subthemes"] = analyzer.split_theme_values(item.get("subthemes"))
        cleaned.append(item)
    return cleaned


def _infer_market(item: dict[str, Any]) -> str:
    market = str(item.get("market", "") or "").strip().upper()
    if market:
        return market
    ticker = str(item.get("ticker", "")).upper()
    if ticker.endswith(".KS"):
        return "KOSPI"
    if ticker.endswith(".KQ"):
        return "KOSDAQ"
    return "NASDAQ" if ticker else ""


def _priority_weight(priority: Any) -> int:
    return PRIORITY_WEIGHTS.get(str(priority or "").strip().upper(), 0)


def _is_representative(item: dict[str, Any]) -> bool:
    return "대표" in str(item.get("role", ""))


def _is_direct_benefit(item: dict[str, Any]) -> bool:
    return "직접" in str(item.get("benefit_type", ""))


def group_theme_universe_by_theme(rows: list[dict[str, Any]] | None = None, logger: Logger = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    source_rows = rows if rows is not None else load_theme_universe_rows(logger=logger)
    for row in source_rows:
        for theme in analyzer.split_theme_values(row.get("themes")):
            ticker_key = analyzer.normalize_text(str(row.get("ticker", "")))
            if not theme or not ticker_key or ticker_key in seen[theme]:
                continue
            grouped[theme].append(row)
            seen[theme].add(ticker_key)
    return dict(grouped)


def _market_mix(rows: list[dict[str, Any]]) -> str:
    markets = []
    for market in SUPPORTED_MARKETS:
        if any(str(row.get("market", "")).upper() == market for row in rows):
            markets.append(market)
    for row in rows:
        market = str(row.get("market", "") or "").strip().upper()
        if market and market not in markets:
            markets.append(market)
    if not markets:
        return "데이터 부족"
    return markets[0] if len(markets) == 1 else f"{'/'.join(markets)} 혼합"


def _theme_mention_scores(news_summary: dict[str, Any], theme_config: dict[str, Any], theme_names: list[str]) -> dict[str, float]:
    raw_scores: dict[str, float] = {theme: 0.0 for theme in theme_names}

    def add(raw_theme: Any, weight: float) -> None:
        if not raw_theme:
            return
        canonical = analyzer.canonical_theme(str(raw_theme), theme_config)
        raw_norm = analyzer.normalize_text(str(raw_theme))
        canonical_norm = analyzer.normalize_text(canonical)
        for theme in theme_names:
            theme_norm = analyzer.normalize_text(theme)
            if theme_norm in {raw_norm, canonical_norm} or raw_norm in theme_norm or theme_norm in raw_norm:
                raw_scores[theme] = raw_scores.get(theme, 0.0) + weight

    raw_themes = news_summary.get("themes", [])
    if isinstance(raw_themes, list):
        for item in raw_themes:
            add(item.get("name") or item.get("theme") if isinstance(item, dict) else item, 3.0)

    key_news = news_summary.get("key_news", [])
    if isinstance(key_news, list):
        for news in key_news:
            if not isinstance(news, dict):
                continue
            for theme in news.get("themes", []) if isinstance(news.get("themes", []), list) else []:
                add(theme, 2.0)

    max_score = max(raw_scores.values(), default=0.0)
    if max_score <= 0:
        return {theme: 0.0 for theme in theme_names}
    return {theme: analyzer.clamp(score / max_score * 30, 0, 30) for theme, score in raw_scores.items()}


def _analysis_for_item(item: dict[str, Any], strong_themes: list[str], market_state: str, cache: dict[str, Any]) -> Any:
    ticker = analyzer.normalize_ticker_symbol(str(item.get("ticker", "")))
    key = analyzer.normalize_text(ticker)
    if key not in cache:
        cache[key] = analyzer.analyze_stock(item, strong_themes, market_state)
    return cache[key]


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _score_return_component(avg_return: float | None) -> int:
    if avg_return is None:
        return 0
    return analyzer.clamp(((avg_return + 3.0) / 10.0) * 25, 0, 25)


def _score_volume_component(avg_volume_ratio: float | None) -> int:
    if avg_volume_ratio is None:
        return 0
    return analyzer.clamp(((avg_volume_ratio - 0.8) / 1.7) * 20, 0, 20)


def score_theme_groups(context: Any, rows: list[dict[str, Any]] | None = None, logger: Logger = None) -> list[dict[str, Any]]:
    universe_rows = rows if rows is not None else load_theme_universe_rows(logger=logger)
    groups = group_theme_universe_by_theme(universe_rows)
    if not groups:
        return []

    news_scores = _theme_mention_scores(context.news_summary, context.theme_config, list(groups.keys()))
    analysis_cache: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    base_strong_themes = list(dict.fromkeys([*context.strong_themes, *groups.keys()]))

    for theme, theme_rows in groups.items():
        analyses = [
            _analysis_for_item(row, base_strong_themes, context.market.state, analysis_cache)
            for row in theme_rows
        ]
        valid = [item for item in analyses if not getattr(item, "error", None)]
        change_values = [float(item.change_pct) for item in valid if item.change_pct is not None]
        volume_values = [float(item.metrics.get("volume_ratio", 0.0) or 0.0) for item in valid if item.metrics]
        avg_return = _avg(change_values) if change_values else None
        avg_volume_ratio = _avg(volume_values) if volume_values else None

        representative_rows = [row for row in theme_rows if _is_representative(row)]
        representative_tickers = {analyzer.normalize_text(str(row.get("ticker", ""))) for row in representative_rows}
        representative_valid = [
            item for item in valid
            if analyzer.normalize_text(str(item.ticker)) in representative_tickers
        ]
        representative_change = _avg([
            float(item.change_pct)
            for item in representative_valid
            if item.change_pct is not None
        ]) if representative_valid else None
        representative_score = analyzer.clamp(((representative_change or 0.0) + 2.0) / 7.0 * 10, 0, 10) if representative_valid else 0

        direct_ratio = sum(1 for row in theme_rows if _is_direct_benefit(row)) / len(theme_rows)
        direct_score = analyzer.clamp(direct_ratio * 10, 0, 10)
        avg_priority = _avg([_priority_weight(row.get("priority")) for row in theme_rows])
        priority_score = analyzer.clamp(avg_priority, 0, 5)
        mention_score = int(news_scores.get(theme, 0))
        return_score = _score_return_component(avg_return)
        volume_score = _score_volume_component(avg_volume_ratio)
        total_score = analyzer.clamp(
            mention_score + return_score + volume_score + representative_score + direct_score + priority_score
        )

        leaders = sorted(
            valid,
            key=lambda item: (
                item.change_pct if item.change_pct is not None else -999,
                item.metrics.get("volume_ratio", 0.0) if item.metrics else 0.0,
                item.composite_score,
            ),
            reverse=True,
        )[:3]
        if not leaders:
            leaders = sorted(analyses, key=lambda item: item.composite_score, reverse=True)[:3]

        evidence: list[str] = []
        if avg_return is not None:
            evidence.append(f"평균 상승률 {analyzer.format_pct(avg_return)}")
        else:
            evidence.append("상승률 데이터 부족")
        if avg_volume_ratio is not None:
            evidence.append(f"거래량 {avg_volume_ratio:.1f}배")
        else:
            evidence.append("거래량 데이터 부족")
        if representative_score:
            evidence.append("대표종목 강세")
        if direct_score >= 5:
            evidence.append("직접수혜 비중 높음")
        if priority_score >= 4:
            evidence.append("priority S/A 중심")
        if mention_score:
            evidence.append("뉴스/테마 언급")

        results.append(
            {
                "theme": theme,
                "score": total_score,
                "market_mix": _market_mix(theme_rows),
                "rows": theme_rows,
                "leaders": leaders,
                "evidence": evidence,
                "components": {
                    "mention": mention_score,
                    "return": return_score,
                    "volume": volume_score,
                    "representative": representative_score,
                    "direct_benefit": direct_score,
                    "priority": priority_score,
                },
                "avg_return": avg_return,
                "avg_volume_ratio": avg_volume_ratio,
                "data_points": len(valid),
                "total_count": len(theme_rows),
            }
        )

    return sorted(results, key=lambda item: (item["score"], item["data_points"], item["total_count"]), reverse=True)


def _stock_meta_by_ticker(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = analyzer.normalize_text(str(row.get("ticker", "")))
        if not key:
            continue
        current = meta.get(key)
        if current is None or _priority_weight(row.get("priority")) > _priority_weight(current.get("priority")):
            meta[key] = row
    return meta


def _watchlist_tickers(items: list[dict[str, Any]]) -> set[str]:
    return {analyzer.normalize_text(str(item.get("ticker", ""))) for item in items if str(item.get("ticker", "")).strip()}


def _holding_tickers(items: list[dict[str, Any]]) -> set[str]:
    return {analyzer.normalize_text(str(item.get("ticker", ""))) for item in items if str(item.get("ticker", "")).strip()}


def _stock_candidate_score(
    analysis: Any,
    theme_score: int,
    meta: dict[str, Any],
    *,
    in_watchlist: bool = False,
) -> tuple[int, list[str]]:
    change_score = _score_return_component(analysis.change_pct)
    volume_score = _score_volume_component(float(analysis.metrics.get("volume_ratio", 0.0) or 0.0) if analysis.metrics else None)
    role_score = 8 if _is_representative(meta) else 3 if str(meta.get("role", "")).strip() else 0
    benefit_score = 7 if _is_direct_benefit(meta) else 3 if str(meta.get("benefit_type", "")).strip() else 0
    priority_score = _priority_weight(meta.get("priority"))
    watchlist_score = 5 if in_watchlist else 0
    total = analyzer.clamp(
        theme_score * 0.35
        + change_score
        + volume_score
        + role_score
        + benefit_score
        + priority_score
        + watchlist_score
    )

    cautions: list[str] = []
    if analysis.change_pct is None or not analysis.metrics:
        cautions.append("데이터 부족")
    elif volume_score < 4:
        cautions.append("거래량 약함")
    if analysis.change_pct is not None and analysis.change_pct >= 8:
        cautions.append("단기 과열 주의")
    return total, cautions


def _market_for_ticker(ticker: str, meta: dict[str, Any] | None = None) -> str:
    if meta and meta.get("market"):
        return str(meta.get("market"))
    ticker = ticker.upper()
    if ticker.endswith(".KS"):
        return "KOSPI"
    if ticker.endswith(".KQ"):
        return "KOSDAQ"
    return "NASDAQ" if ticker else "-"


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


def _theme_universe_stock_item(
    ticker: str,
    universe_theme: str,
    theme_map: dict[str, dict[str, Any]],
    ticker_map: dict[str, str],
    row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_ticker = analyzer.normalize_ticker_symbol(ticker)
    row = row or {}
    name = str(row.get("name") or "").strip() or _stock_name_from_ticker(normalized_ticker, ticker_map)
    payload, mapped_name = storage.find_theme_mapping(normalized_ticker, normalized_ticker, theme_map=theme_map, ticker_map=ticker_map)

    themes: list[str] = analyzer.split_theme_values(row.get("themes"))
    subthemes: list[str] = analyzer.split_theme_values(row.get("subthemes"))
    if isinstance(payload, dict):
        for theme in analyzer.split_theme_values(payload.get("themes")):
            if theme not in themes:
                themes.append(theme)
        for subtheme in analyzer.split_theme_values(payload.get("subthemes")):
            if subtheme not in subthemes:
                subthemes.append(subtheme)
        if mapped_name and name == normalized_ticker:
            name = mapped_name

    if universe_theme not in themes:
        themes.append(universe_theme)
    if universe_theme not in subthemes:
        subthemes.append(universe_theme)

    return {
        "name": name,
        "ticker": normalized_ticker,
        "market": _infer_market({"ticker": normalized_ticker, **row}),
        "themes": themes,
        "subthemes": subthemes,
        "benefit_type": str(row.get("benefit_type", "")),
        "role": str(row.get("role", "")),
        "priority": str(row.get("priority", "")),
        "status": str(row.get("status", "active") or "active"),
        "memo": str(row.get("memo", "")),
        "source": f"theme_universe:{universe_theme}",
    }


def theme_universe_candidate_items(strong_themes: list[str], theme_config: dict[str, Any], logger: Logger = None) -> list[dict[str, Any]]:
    rows = load_theme_universe_rows(logger=logger)
    groups = group_theme_universe_by_theme(rows)
    if not groups or not strong_themes:
        return []

    theme_map = storage.load_theme_map(logger=logger)
    ticker_map = storage.load_ticker_map(logger=logger)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for universe_theme, theme_rows in groups.items():
        if not any(_theme_matches(theme, universe_theme, theme_config) for theme in strong_themes):
            continue
        added = 0
        for row in theme_rows:
            ticker = str(row.get("ticker", ""))
            normalized_ticker = analyzer.normalize_ticker_symbol(str(ticker))
            key = analyzer.normalize_text(normalized_ticker)
            if not normalized_ticker or key in seen:
                continue
            candidates.append(_theme_universe_stock_item(normalized_ticker, universe_theme, theme_map, ticker_map, row=row))
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
    global _LAST_RECOMMENDATION_META_BY_TICKER
    universe_rows = load_theme_universe_rows(logger=logger)
    _LAST_RECOMMENDATION_META_BY_TICKER = _stock_meta_by_ticker(universe_rows)
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


def select_top_recommendations_with_theme_universe(
    watchlist: list[Any],
    holdings: list[dict[str, Any]] | None = None,
) -> list[Any]:
    candidates = _LAST_RECOMMENDATION_CANDIDATES or watchlist
    held_tickers = _holding_tickers(holdings or [])
    watchlist_tickers = {analyzer.normalize_text(str(item.ticker)) for item in watchlist}
    strong_theme_score = 70
    ranked: list[tuple[int, Any]] = []
    for item in candidates:
        ticker_key = analyzer.normalize_text(str(item.ticker))
        if item.error or ticker_key in held_tickers:
            continue
        matched_meta = _LAST_RECOMMENDATION_META_BY_TICKER.get(ticker_key, {})
        item_theme_score = strong_theme_score
        score, cautions = _stock_candidate_score(
            item,
            item_theme_score,
            matched_meta,
            in_watchlist=ticker_key in watchlist_tickers,
        )
        if score < 35 and len(ranked) >= 3:
            continue
        item.metrics["phase3_recommendation_score"] = float(score)
        item.metrics["phase3_caution_count"] = float(len(cautions))
        ranked.append((score, item))
    if ranked:
        return [item for _, item in sorted(ranked, key=lambda pair: (pair[0], pair[1].composite_score), reverse=True)[:3]]
    return _ORIGINAL_SELECT_TOP(candidates, holdings) if _ORIGINAL_SELECT_TOP else []


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
    rows = load_theme_universe_rows()
    theme_scores = score_theme_groups(context, rows=rows)[:5]
    strong_themes = [item["theme"] for item in theme_scores[:3]] or context.strong_themes
    candidate_items = theme_universe_candidate_items(strong_themes, context.theme_config)
    watchlist_tickers = _watchlist_tickers(context.watchlist_items)
    holding_tickers = _holding_tickers(context.holdings)
    meta_by_ticker = _stock_meta_by_ticker(rows)
    theme_score_by_name = {str(item["theme"]): int(item["score"]) for item in theme_scores}

    if not candidate_items:
        return _ORIGINAL_STRONG_THEME_NAMES()

    ranked: list[tuple[int, Any, dict[str, Any], list[str], str]] = []
    for stock in candidate_items:
        ticker_key = analyzer.normalize_text(str(stock.get("ticker", "")))
        if ticker_key in holding_tickers:
            continue
        analysis = analyzer.analyze_stock(stock, strong_themes, context.market.state)
        if analysis.error:
            continue
        matched_theme = next((theme for theme in stock.get("themes", []) if theme in theme_score_by_name), strong_themes[0] if strong_themes else "-")
        meta = meta_by_ticker.get(ticker_key, stock)
        score, cautions = _stock_candidate_score(
            analysis,
            theme_score_by_name.get(matched_theme, 50),
            meta,
            in_watchlist=ticker_key in watchlist_tickers,
        )
        ranked.append((score, analysis, meta, cautions, matched_theme))

    ranked = sorted(ranked, key=lambda item: (item[0], item[1].composite_score), reverse=True)[:3]
    lines = ["강한테마종목 TOP3:", ""]
    for index, (score, item, meta, cautions, matched_theme) in enumerate(ranked, start=1):
        lines.append(f"{index}. {analyzer.bold(item.name)}")
        lines.append(f"티커: {analyzer.bold(item.ticker)}")
        lines.append(f"시장: {analyzer.bold(_market_for_ticker(item.ticker, meta))}")
        lines.append(f"테마: {analyzer.bold(matched_theme)}")
        lines.append(f"점수: {analyzer.bold(str(score))}")
        if cautions:
            lines.append(f"주의: {', '.join(cautions)}")
        lines.append("")
    if not ranked:
        lines.append("추천 가능 종목 없음")
    lines.extend(
        [
            "기준:",
            analyzer.bold("테마 점수 + 상승률 + 거래량 + role/benefit/priority + 관심종목 가산점"),
            "",
            "데이터 출처:",
            f"* {analyzer.bold('theme_universe 기반')}",
            f"* {analyzer.bold('보유종목 제외')}",
            f"* {analyzer.bold('관심종목 가산')}",
        ]
    )
    return "\n".join(lines)


def strong_themes_report() -> str:
    context = analyzer.build_context()
    rows = load_theme_universe_rows()
    scored = score_theme_groups(context, rows=rows)[:3]
    if not scored:
        return _ORIGINAL_STRONG_THEMES_REPORT() if _ORIGINAL_STRONG_THEMES_REPORT else "데이터 부족"

    lines = analyzer.section("🔥 오늘 강한 테마")
    for index, item in enumerate(scored, start=1):
        leaders = item.get("leaders", [])
        leader_text = ", ".join(str(leader.ticker) for leader in leaders[:3]) if leaders else "데이터 부족"
        evidence = item.get("evidence", [])[:4]
        evidence_text = " / ".join(evidence) if evidence else "데이터 부족"
        lines.append(f"{index}. {analyzer.bold(item['theme'])}")
        lines.append(f"점수: {analyzer.bold(str(item['score']))}")
        lines.append(f"시장: {analyzer.bold(item['market_mix'])}")
        lines.append(f"대표 강세종목: {analyzer.bold(leader_text)}")
        lines.append(f"근거: {evidence_text}")
        if int(item.get("data_points", 0)) == 0:
            lines.append("주의: 데이터 부족")
        lines.append("")

    lines.append("점수 계산:")
    lines.append("* 뉴스/테마 언급 30 + 평균 상승률 25 + 거래량 증가율 20")
    lines.append("* 대표종목 강세 10 + 직접수혜 비중 10 + priority 5")
    return "\n".join(lines).strip()


def theme_check_report(theme: str) -> str:
    context = analyzer.build_context()
    rows = load_theme_universe_rows()
    groups = group_theme_universe_by_theme(rows)
    matched_theme = ""
    for candidate in groups:
        if _theme_matches(theme, candidate, context.theme_config):
            matched_theme = candidate
            break
    if not matched_theme:
        return _ORIGINAL_THEME_CHECK_REPORT(theme) if _ORIGINAL_THEME_CHECK_REPORT else f"{theme}: 데이터 부족"

    theme_rows = groups[matched_theme]
    analysis_cache: dict[str, Any] = {}
    analyses = [_analysis_for_item(row, [matched_theme], context.market.state, analysis_cache) for row in theme_rows]
    valid = [item for item in analyses if not item.error]
    recent_strong = sorted(
        valid,
        key=lambda item: (
            item.change_pct if item.change_pct is not None else -999,
            item.metrics.get("volume_ratio", 0.0) if item.metrics else 0.0,
        ),
        reverse=True,
    )[:5]
    market_counts = Counter(str(row.get("market", "") or "미분류") for row in theme_rows)
    representatives = [row for row in theme_rows if _is_representative(row)]
    direct_benefits = [row for row in theme_rows if _is_direct_benefit(row)]
    avg_rsi = _avg([float(item.metrics.get("rsi", 50.0) or 50.0) for item in valid]) if valid else 50.0
    avg_volume = _avg([float(item.metrics.get("volume_ratio", 0.0) or 0.0) for item in valid if item.metrics]) if valid else 0.0
    overheated = avg_rsi >= 70 or any((item.change_pct or 0) >= 8 for item in valid)

    lines = analyzer.section("🧭 테마점검")
    lines.append(f"테마명: {analyzer.bold(matched_theme)}")
    lines.append(f"총 종목 수: {analyzer.bold(str(len(theme_rows)))}")
    lines.append("")
    lines.append("시장별 분포:")
    for market, count in market_counts.items():
        lines.append(f"* {market}: {analyzer.bold(str(count))}")
    lines.append("")
    lines.append("대표종목:")
    lines.append(", ".join(f"{row.get('name') or row.get('ticker')}({row.get('ticker')})" for row in representatives[:6]) or "데이터 부족")
    lines.append("")
    lines.append("직접수혜 종목:")
    lines.append(", ".join(f"{row.get('name') or row.get('ticker')}({row.get('ticker')})" for row in direct_benefits[:8]) or "데이터 부족")
    lines.append("")
    lines.append("최근 강세 종목:")
    if recent_strong:
        for item in recent_strong[:5]:
            volume_text = f"{item.metrics.get('volume_ratio', 0.0):.1f}배" if item.metrics else "-"
            lines.append(f"* {item.name}({item.ticker}) {analyzer.format_pct(item.change_pct)} / 거래량 {volume_text}")
    else:
        lines.append("* 데이터 부족")
    lines.append("")
    lines.append(f"과열 여부: {analyzer.bold('과열 주의' if overheated else '보통')}")
    lines.append(f"데이터 상태: {analyzer.bold('충분' if valid else '데이터 부족')}")
    if avg_volume and avg_volume < 0.8:
        lines.append("주의: 거래량 확인 필요")
    return "\n".join(lines).strip()


def universe_summary_text(logger: Logger = None) -> str:
    sync_theme_universe_cache(logger=logger, force=True)
    summary = google_sheets_store.theme_universe_summary(logger=logger)
    status = summary.get("sync_status", {})
    status_text = str(status.get("status", "unknown"))
    reason = str(status.get("reason", "") or "")
    synced_at = str(status.get("synced_at", "") or "-")

    lines = analyzer.section("🧭 유니버스 요약")
    lines.append(f"총 종목 수: {analyzer.bold(str(summary.get('total_tickers', 0)))}")
    lines.append("")
    lines.append("시장별 종목 수:")
    market_counts = summary.get("market_counts", {})
    if market_counts:
        for market, count in market_counts.items():
            lines.append(f"* {market}: {analyzer.bold(str(count))}")
    else:
        lines.append("* 캐시에는 시장 정보가 없습니다.")

    lines.append("")
    lines.append("테마별 상위 10개:")
    theme_counts = summary.get("theme_counts", {})
    if theme_counts:
        for theme, count in theme_counts.items():
            lines.append(f"* {theme}: {analyzer.bold(str(count))}")
    else:
        lines.append("* 테마 데이터 없음")

    lines.append("")
    lines.append(f"마지막 동기화 상태: {analyzer.bold(status_text)}")
    lines.append(f"동기화 시각: {analyzer.bold(synced_at)}")
    if reason:
        lines.append(f"사유: {reason}")
    lines.append(f"데이터 기준: {summary.get('source', '-')}")
    return "\n".join(lines).strip()


def patch_analyzer_theme_universe() -> None:
    global _PATCHED
    global _ORIGINAL_ANALYZE_WATCHLIST
    global _ORIGINAL_CONDITION_CANDIDATES
    global _ORIGINAL_DEEP_CANDIDATES
    global _ORIGINAL_EXTRACT_PRIORITY
    global _ORIGINAL_EXTRACT_THEMES
    global _ORIGINAL_SELECT_TOP
    global _ORIGINAL_STRONG_THEME_NAMES
    global _ORIGINAL_STRONG_THEMES_REPORT
    global _ORIGINAL_THEME_CHECK_REPORT

    sync_theme_universe_cache()

    if _PATCHED:
        return

    _ORIGINAL_EXTRACT_PRIORITY = analyzer.extract_priority_theme_payload
    _ORIGINAL_EXTRACT_THEMES = analyzer.extract_themes_from_news
    _ORIGINAL_ANALYZE_WATCHLIST = analyzer.analyze_watchlist
    _ORIGINAL_SELECT_TOP = analyzer.select_top_recommendations
    _ORIGINAL_DEEP_CANDIDATES = analyzer.build_deep_analysis_candidates
    _ORIGINAL_CONDITION_CANDIDATES = analyzer.build_condition_search_candidates
    _ORIGINAL_STRONG_THEME_NAMES = analyzer.strong_theme_stock_names
    _ORIGINAL_STRONG_THEMES_REPORT = analyzer.strong_themes_report
    _ORIGINAL_THEME_CHECK_REPORT = analyzer.theme_check_report

    analyzer.extract_priority_theme_payload = extract_priority_theme_payload
    analyzer.extract_themes_from_news = extract_themes_from_news
    analyzer.analyze_watchlist = analyze_watchlist_with_theme_universe
    analyzer.select_top_recommendations = select_top_recommendations_with_theme_universe
    analyzer.build_deep_analysis_candidates = build_deep_analysis_candidates
    analyzer.build_condition_search_candidates = build_condition_search_candidates
    analyzer.strong_theme_stock_names = strong_theme_stock_names
    analyzer.strong_themes_report = strong_themes_report
    analyzer.theme_check_report = theme_check_report
    _PATCHED = True
