from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from config import (
    ALERTS_FILE,
    HOLDINGS_FILE,
    NEWS_SUMMARY_FILE,
    RECOMMENDATION_HISTORY_FILE,
    THEME_CONFIG_FILE,
    THEME_MAP_FILE,
    TICKER_MAP_FILE,
    TRADE_HISTORY_FILE,
    WATCHLIST_FILE,
)
import sheets_storage


PROJECT_ROOT = Path(__file__).resolve().parent
BASE_DIR = PROJECT_ROOT
Logger = Callable[[str], None] | None
SHEETS_TABLES = {
    WATCHLIST_FILE: "watchlist",
    HOLDINGS_FILE: "holdings",
    TRADE_HISTORY_FILE: "trade_history",
    RECOMMENDATION_HISTORY_FILE: "recommendation_history",
}


def describe_payload(payload: Any) -> str:
    if isinstance(payload, list):
        return f"{len(payload)}개 항목"
    if isinstance(payload, dict):
        return f"{len(payload)}개 키"
    return type(payload).__name__


def log(logger: Logger, message: str) -> None:
    if logger:
        logger(message)


def json_file_path(file_name: str) -> Path:
    return PROJECT_ROOT / file_name


def json_file_path_text(file_name: str) -> str:
    return str(json_file_path(file_name))


def storage_location_text(file_name: str) -> str:
    table_name = SHEETS_TABLES.get(file_name)
    if table_name and sheets_storage.is_configured():
        return f"Google Sheets:{table_name} / cache:{json_file_path(file_name)}"
    return str(json_file_path(file_name))


def _load_local_json_file(file_name: str, default: Any, *, required: bool = False, logger: Logger = None) -> Any:
    path = json_file_path(file_name)
    if not path.exists():
        level = "필수" if required else "선택"
        log(logger, f"{file_name} 로드 실패: {level} 파일이 없습니다. 경로: {path}")
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        log(logger, f"{file_name} 로드 실패: JSON 파싱 오류 - {exc}. 경로: {path}")
        return default

    log(logger, f"{file_name} 로드 성공: {describe_payload(payload)} / 경로: {path}")
    return payload


def load_json_file(file_name: str, default: Any, *, required: bool = False, logger: Logger = None) -> Any:
    table_name = SHEETS_TABLES.get(file_name)
    if table_name and sheets_storage.is_configured():
        try:
            payload = sheets_storage.load_records(table_name)
            if payload == [] and isinstance(default, list):
                local_payload = _load_local_json_file(file_name, default, logger=None)
                if isinstance(local_payload, list) and local_payload:
                    sheets_storage.save_records(table_name, local_payload)
                    payload = local_payload
                    log(logger, f"{file_name} Google Sheets 초기 동기화 성공: 로컬 캐시 {describe_payload(payload)} -> sheet: {table_name}")
            log(logger, f"{file_name} Google Sheets 로드 성공: {describe_payload(payload)} / sheet: {table_name}")
            return payload
        except Exception as exc:
            log(logger, f"{file_name} Google Sheets 로드 실패: {exc}. 로컬 캐시로 진행합니다.")

    return _load_local_json_file(file_name, default, required=required, logger=logger)


def save_json_file(file_name: str, payload: Any, logger: Logger = None) -> None:
    path = json_file_path(file_name)
    table_name = SHEETS_TABLES.get(file_name)
    if table_name and sheets_storage.is_configured():
        if not isinstance(payload, list):
            raise ValueError(f"{file_name}은 Google Sheets 저장 시 목록 형식이어야 합니다.")
        sheets_storage.save_records(table_name, payload)
        log(logger, f"{file_name} Google Sheets 저장 성공: {describe_payload(payload)} / sheet: {table_name}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    log(logger, f"{file_name} 저장 성공: {describe_payload(payload)} / 경로: {path}")


def normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "")


def load_watchlist(logger: Logger = None) -> list[dict[str, Any]]:
    payload = load_json_file(WATCHLIST_FILE, [], required=True, logger=logger)
    if not isinstance(payload, list):
        log(logger, f"{WATCHLIST_FILE} 로드 실패: 목록 형식이 아닙니다. 저장소: {storage_location_text(WATCHLIST_FILE)}")
        return []
    return payload


def save_watchlist(items: list[dict[str, Any]], logger: Logger = None) -> None:
    save_json_file(WATCHLIST_FILE, items, logger=logger)


def load_holdings(logger: Logger = None) -> list[dict[str, Any]]:
    payload = load_json_file(HOLDINGS_FILE, [], required=True, logger=logger)
    if not isinstance(payload, list):
        log(logger, f"{HOLDINGS_FILE} 로드 실패: 목록 형식이 아닙니다. 저장소: {storage_location_text(HOLDINGS_FILE)}")
        return []
    return payload


def save_holdings(items: list[dict[str, Any]], logger: Logger = None) -> None:
    save_json_file(HOLDINGS_FILE, items, logger=logger)


def load_trade_history(logger: Logger = None) -> list[dict[str, Any]]:
    payload = load_json_file(TRADE_HISTORY_FILE, [], logger=logger)
    if not isinstance(payload, list):
        log(logger, f"{TRADE_HISTORY_FILE} 로드 실패: 목록 형식이 아닙니다. 저장소: {storage_location_text(TRADE_HISTORY_FILE)}")
        return []
    return payload


def save_trade_history(items: list[dict[str, Any]], logger: Logger = None) -> None:
    save_json_file(TRADE_HISTORY_FILE, items, logger=logger)


def load_recommendation_history(logger: Logger = None) -> list[dict[str, Any]]:
    payload = load_json_file(RECOMMENDATION_HISTORY_FILE, [], logger=logger)
    if not isinstance(payload, list):
        log(logger, f"{RECOMMENDATION_HISTORY_FILE} 로드 실패: 목록 형식이 아닙니다. 저장소: {storage_location_text(RECOMMENDATION_HISTORY_FILE)}")
        return []
    return payload


def save_recommendation_history(items: list[dict[str, Any]], logger: Logger = None) -> None:
    save_json_file(RECOMMENDATION_HISTORY_FILE, items, logger=logger)


def load_news_summary(logger: Logger = None) -> dict[str, Any]:
    return load_json_file(NEWS_SUMMARY_FILE, {}, logger=logger)


def load_alerts(logger: Logger = None) -> list[dict[str, Any]]:
    return load_json_file(ALERTS_FILE, [], logger=logger)


def save_alerts(items: list[dict[str, Any]]) -> None:
    save_json_file(ALERTS_FILE, items)


def load_ticker_map(logger: Logger = None) -> dict[str, str]:
    payload = load_json_file(TICKER_MAP_FILE, {}, logger=logger)
    if not isinstance(payload, dict):
        log(logger, f"{TICKER_MAP_FILE} 로드 실패: 객체 형식이 아닙니다. 기본값으로 진행합니다.")
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def load_theme_map(logger: Logger = None) -> dict[str, dict[str, Any]]:
    payload = load_json_file(THEME_MAP_FILE, {}, logger=logger)
    if not isinstance(payload, dict):
        log(logger, f"{THEME_MAP_FILE} 로드 실패: 객체 형식이 아닙니다. 기본값으로 진행합니다.")
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalized[str(key)] = value
    return normalized


def load_theme_config(logger: Logger = None) -> dict[str, Any]:
    payload = load_json_file(THEME_CONFIG_FILE, {}, logger=logger)
    if not isinstance(payload, dict):
        log(logger, f"{THEME_CONFIG_FILE} 로드 실패: 객체 형식이 아닙니다. 기본값으로 진행합니다.")
        return {}
    return payload


def resolve_ticker(query: str, ticker_map: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    ticker_map = ticker_map or load_ticker_map()
    normalized_query = normalize(query)
    for name, ticker in ticker_map.items():
        normalized_ticker = normalize(ticker)
        if normalize(name) == normalized_query:
            return ticker, name
        if normalized_ticker == normalized_query:
            return ticker, name
        if normalized_query.isdigit() and normalized_ticker.startswith(f"{normalized_query}."):
            return ticker, name
    return None, None


def find_theme_mapping(
    query: str,
    ticker: str | None = None,
    *,
    theme_map: dict[str, dict[str, Any]] | None = None,
    ticker_map: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    theme_map = theme_map or load_theme_map()
    ticker_map = ticker_map or load_ticker_map()
    candidates = [query]
    if ticker:
        candidates.append(ticker)

    for name, mapped_ticker in ticker_map.items():
        if ticker and normalize(mapped_ticker) == normalize(ticker):
            candidates.append(name)
        if normalize(name) == normalize(query):
            candidates.append(name)
            candidates.append(mapped_ticker)

    normalized_candidates = {normalize(candidate) for candidate in candidates if candidate}
    for name, payload in theme_map.items():
        if normalize(name) in normalized_candidates:
            return payload, name
    return None, None


def find_item(items: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    normalized_query = normalize(query)
    for item in items:
        if normalize(str(item.get("name", ""))) == normalized_query:
            return item
        if normalize(str(item.get("ticker", ""))) == normalized_query:
            return item
    return None


def item_keys(item: dict[str, Any]) -> set[str]:
    return {
        normalize(str(value))
        for value in (item.get("name"), item.get("ticker"))
        if str(value or "").strip()
    }


def prune_watchlist_holdings_overlap(logger: Logger = None) -> list[dict[str, Any]]:
    watchlist = load_watchlist(logger=logger)
    holdings = load_holdings(logger=logger)
    holding_keys: set[str] = set()
    for holding in holdings:
        holding_keys.update(item_keys(holding))

    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for item in watchlist:
        if item_keys(item) & holding_keys:
            removed.append(item)
        else:
            kept.append(item)

    if removed:
        save_watchlist(kept, logger=logger)
        names = ", ".join(str(item.get("name", "-")) for item in removed)
        log(logger, f"관심/보유 중복 정리 완료: {names}")
    return removed


def upsert_watchlist(
    name: str,
    ticker: str,
    themes: list[str] | None = None,
    subthemes: list[str] | None = None,
    non_priority_themes: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    items = load_watchlist()
    existing = find_item(items, name) or find_item(items, ticker)
    payload: dict[str, Any] = {"name": name, "ticker": ticker}
    if themes is not None:
        payload["themes"] = themes
    if subthemes is not None:
        payload["subthemes"] = subthemes
    if non_priority_themes:
        payload["non_priority_themes"] = non_priority_themes
    if existing:
        existing.update(payload)
        save_watchlist(items)
        return "updated", existing

    items.append(payload)
    save_watchlist(items)
    return "added", payload


def delete_watchlist(query: str) -> dict[str, Any] | None:
    items = load_watchlist()
    target = find_item(items, query)
    if not target:
        return None

    save_watchlist([item for item in items if item is not target])
    return target


def upsert_holding(
    name: str,
    ticker: str,
    quantity: int,
    average_price: float,
    themes: list[str] | None = None,
    subthemes: list[str] | None = None,
    non_priority_themes: list[str] | None = None,
    logger: Logger = None,
) -> tuple[str, dict[str, Any]]:
    status, item, _ = buy_holding(
        name,
        ticker,
        quantity,
        average_price,
        themes,
        subthemes,
        non_priority_themes,
        logger=logger,
    )
    return ("updated" if status == "additional_buy" else "added"), item


def buy_holding(
    name: str,
    ticker: str,
    quantity: int,
    buy_price: float,
    themes: list[str] | None = None,
    subthemes: list[str] | None = None,
    non_priority_themes: list[str] | None = None,
    logger: Logger = None,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    items = load_holdings(logger=logger)
    existing = find_item(items, ticker) or find_item(items, name)
    buy_quantity = int(quantity)
    buy_price_value = float(buy_price)
    if buy_quantity <= 0:
        raise ValueError("수량은 1 이상이어야 합니다.")
    if buy_price_value <= 0:
        raise ValueError("매수가는 0보다 커야 합니다.")

    if existing:
        before = existing.copy()
        old_quantity = int(existing.get("quantity", 0) or 0)
        old_average_price = float(existing.get("avg_price", existing.get("average_price", 0)) or 0)
        new_quantity = old_quantity + buy_quantity
        new_average_price = (
            (old_quantity * old_average_price) + (buy_quantity * buy_price_value)
        ) / new_quantity

        existing["name"] = str(existing.get("name") or name)
        existing["ticker"] = str(existing.get("ticker") or ticker)
        existing["quantity"] = new_quantity
        existing["avg_price"] = new_average_price
        if themes is not None and not existing.get("themes"):
            existing["themes"] = themes
        if subthemes is not None and not existing.get("subthemes"):
            existing["subthemes"] = subthemes
        if non_priority_themes and not existing.get("non_priority_themes"):
            existing["non_priority_themes"] = non_priority_themes

        save_holdings(items, logger=logger)
        return "additional_buy", existing, before

    payload: dict[str, Any] = {
        "name": name,
        "ticker": ticker,
        "quantity": buy_quantity,
        "avg_price": buy_price_value,
    }
    if themes is not None:
        payload["themes"] = themes
    if subthemes is not None:
        payload["subthemes"] = subthemes
    if non_priority_themes:
        payload["non_priority_themes"] = non_priority_themes

    items.append(payload)
    save_holdings(items, logger=logger)
    return "new_buy", payload, None


def replace_holding(
    name: str,
    ticker: str,
    quantity: int,
    average_price: float,
    themes: list[str] | None = None,
    subthemes: list[str] | None = None,
    non_priority_themes: list[str] | None = None,
    logger: Logger = None,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    items = load_holdings(logger=logger)
    existing = find_item(items, ticker) or find_item(items, name)
    payload: dict[str, Any] = {
        "name": name,
        "ticker": ticker,
        "quantity": int(quantity),
        "avg_price": float(average_price),
    }
    if payload["quantity"] <= 0:
        raise ValueError("수량은 1 이상이어야 합니다.")
    if payload["avg_price"] <= 0:
        raise ValueError("평단은 0보다 커야 합니다.")
    if themes is not None:
        payload["themes"] = themes
    if subthemes is not None:
        payload["subthemes"] = subthemes
    if non_priority_themes:
        payload["non_priority_themes"] = non_priority_themes

    if existing:
        before = existing.copy()
        existing.clear()
        existing.update(payload)
        save_holdings(items, logger=logger)
        return "manual_update", existing, before

    items.append(payload)
    save_holdings(items, logger=logger)
    return "manual_add", payload, None


def verify_holding_saved(name: str, ticker: str, logger: Logger = None) -> dict[str, Any] | None:
    items = load_holdings(logger=logger)
    target = find_item(items, name) or find_item(items, ticker)
    if target:
        log(logger, f"보유 데이터 저장 검증 성공: {target.get('name', name)} / {target.get('ticker', ticker)} / 총 {len(items)}개 / 저장소: {storage_location_text(HOLDINGS_FILE)}")
    else:
        log(logger, f"보유 데이터 저장 검증 실패: {name} / {ticker} / 총 {len(items)}개 / 저장소: {storage_location_text(HOLDINGS_FILE)}")
    return target


def verify_holding_removed(name: str, ticker: str, logger: Logger = None) -> bool:
    items = load_holdings(logger=logger)
    target = find_item(items, name) or find_item(items, ticker)
    removed = target is None
    if removed:
        log(logger, f"보유 데이터 제거 검증 성공: {name} / {ticker} / 총 {len(items)}개 / 저장소: {storage_location_text(HOLDINGS_FILE)}")
    else:
        log(logger, f"보유 데이터 제거 검증 실패: {name} / {ticker} / 총 {len(items)}개 / 저장소: {storage_location_text(HOLDINGS_FILE)}")
    return removed


def record_trade(entry: dict[str, Any], logger: Logger = None) -> dict[str, Any]:
    history = load_trade_history(logger=logger)
    history.append(entry)
    save_trade_history(history, logger=logger)
    return entry


def verify_trade_saved(entry: dict[str, Any], logger: Logger = None) -> bool:
    history = load_trade_history(logger=logger)
    target = None
    for item in reversed(history):
        if (
            item.get("date") == entry.get("date")
            and item.get("type") == entry.get("type")
            and item.get("ticker") == entry.get("ticker")
            and item.get("quantity") == entry.get("quantity")
            and item.get("price") == entry.get("price")
        ):
            target = item
            break
    if target:
        log(logger, f"{TRADE_HISTORY_FILE} 저장 검증 성공: {entry.get('type')} / {entry.get('name')} / 총 {len(history)}건")
        return True
    log(logger, f"{TRADE_HISTORY_FILE} 저장 검증 실패: {entry.get('type')} / {entry.get('name')} / 총 {len(history)}건")
    return False


def delete_holding(query: str) -> dict[str, Any] | None:
    items = load_holdings()
    target = find_item(items, query)
    if not target:
        return None

    save_holdings([item for item in items if item is not target])
    return target


def add_alert(name: str, condition: str, price: float) -> dict[str, Any]:
    alerts = load_alerts()
    payload = {
        "name": name,
        "condition": condition,
        "price": float(price),
    }
    alerts.append(payload)
    save_alerts(alerts)
    return payload
