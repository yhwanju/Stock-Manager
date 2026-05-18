from __future__ import annotations

from typing import Any, Callable

import storage


Logger = Callable[[str], None] | None
THEME_UNIVERSE_FILE = "theme_universe.json"
UNCLASSIFIED_LABEL = "미분류"


def _emit(logger: Logger, message: str) -> None:
    if logger:
        logger(message)
    else:
        print(message, flush=True)


def is_unclassified_theme(value: Any) -> bool:
    if value is None:
        return True
    values = value if isinstance(value, list) else [value]
    labels = [str(item).strip() for item in values if str(item).strip()]
    if not labels:
        return True
    return all(storage.normalize(label) == storage.normalize(UNCLASSIFIED_LABEL) for label in labels)


def _ticker_key(value: Any) -> str:
    return storage.normalize(str(value or "").strip().upper())


def _ticker_theme_index_from_universe(logger: Logger = None) -> dict[str, str]:
    payload = storage.load_json_file(THEME_UNIVERSE_FILE, {}, logger=logger)
    if not isinstance(payload, dict):
        _emit(logger, f"{THEME_UNIVERSE_FILE} 형식 오류: 객체가 아닙니다.")
        return {}

    index: dict[str, str] = {}
    for theme, tickers in payload.items():
        if not isinstance(tickers, list):
            continue
        for ticker in tickers:
            key = _ticker_key(ticker)
            if key and key not in index:
                index[key] = str(theme).strip()
    return index


def _patch_item_theme_from_universe(item: dict[str, Any], index: dict[str, str], logger: Logger = None) -> bool:
    ticker = str(item.get("ticker", "")).strip().upper()
    theme = index.get(_ticker_key(ticker))
    if not theme:
        return False

    current_themes = item.get("themes", item.get("theme"))
    if not is_unclassified_theme(current_themes):
        return False

    before = UNCLASSIFIED_LABEL
    if isinstance(current_themes, list) and current_themes:
        before = ", ".join(str(value) for value in current_themes)
    elif isinstance(current_themes, str) and current_themes.strip():
        before = current_themes.strip()

    item["themes"] = [theme]
    if "theme" in item:
        item["theme"] = theme

    name = str(item.get("name") or ticker or "-")
    _emit(logger, f"[테마 자동 보정]\n{name}:\n{before} → {theme}")
    return True


def auto_patch_themes_from_universe(
    items: list[dict[str, Any]],
    *,
    logger: Logger = None,
) -> tuple[list[dict[str, Any]], int]:
    index = _ticker_theme_index_from_universe(logger=logger)
    if not index or not isinstance(items, list):
        return items, 0

    updated = 0
    for item in items:
        if isinstance(item, dict) and _patch_item_theme_from_universe(item, index, logger=logger):
            updated += 1
    return items, updated


def patch_watchlist_themes(logger: Logger = None) -> int:
    items = storage.load_watchlist(logger=logger)
    patched_items, updated = auto_patch_themes_from_universe(items, logger=logger)
    if not updated:
        return 0

    storage.save_watchlist(patched_items, logger=logger)
    verified = storage.load_watchlist(logger=logger)
    _emit(logger, f"watchlist 테마 자동 보정 저장 후 재로드 검증: {len(verified)}개")
    return updated


def patch_holdings_themes(logger: Logger = None) -> int:
    items = storage.load_holdings(logger=logger)
    patched_items, updated = auto_patch_themes_from_universe(items, logger=logger)
    if not updated:
        return 0

    storage.save_holdings(patched_items, logger=logger)
    verified = storage.load_holdings(logger=logger)
    _emit(logger, f"holdings 테마 자동 보정 저장 후 재로드 검증: {len(verified)}개")
    return updated


def patch_all_themes(logger: Logger = None) -> tuple[int, int]:
    watchlist_updated = patch_watchlist_themes(logger=logger)
    holdings_updated = patch_holdings_themes(logger=logger)
    return watchlist_updated, holdings_updated
