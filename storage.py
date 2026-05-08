from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from config import ALERTS_FILE, HOLDINGS_FILE, NEWS_SUMMARY_FILE, WATCHLIST_FILE


BASE_DIR = Path(__file__).resolve().parent
Logger = Callable[[str], None] | None


def describe_payload(payload: Any) -> str:
    if isinstance(payload, list):
        return f"{len(payload)}개 항목"
    if isinstance(payload, dict):
        return f"{len(payload)}개 키"
    return type(payload).__name__


def log(logger: Logger, message: str) -> None:
    if logger:
        logger(message)


def load_json_file(file_name: str, default: Any, *, required: bool = False, logger: Logger = None) -> Any:
    path = BASE_DIR / file_name
    if not path.exists():
        level = "필수" if required else "선택"
        log(logger, f"{file_name} 로드 실패: {level} 파일이 없습니다. 기본값으로 진행합니다.")
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        log(logger, f"{file_name} 로드 실패: JSON 파싱 오류 - {exc}. 기본값으로 진행합니다.")
        return default

    log(logger, f"{file_name} 로드 성공: {describe_payload(payload)}")
    return payload


def save_json_file(file_name: str, payload: Any) -> None:
    path = BASE_DIR / file_name
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "")


def load_watchlist(logger: Logger = None) -> list[dict[str, Any]]:
    return load_json_file(WATCHLIST_FILE, [], required=True, logger=logger)


def save_watchlist(items: list[dict[str, Any]]) -> None:
    save_json_file(WATCHLIST_FILE, items)


def load_holdings(logger: Logger = None) -> list[dict[str, Any]]:
    return load_json_file(HOLDINGS_FILE, [], required=True, logger=logger)


def save_holdings(items: list[dict[str, Any]]) -> None:
    save_json_file(HOLDINGS_FILE, items)


def load_news_summary(logger: Logger = None) -> dict[str, Any]:
    return load_json_file(NEWS_SUMMARY_FILE, {}, logger=logger)


def load_alerts(logger: Logger = None) -> list[dict[str, Any]]:
    return load_json_file(ALERTS_FILE, [], logger=logger)


def save_alerts(items: list[dict[str, Any]]) -> None:
    save_json_file(ALERTS_FILE, items)


def find_item(items: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    normalized_query = normalize(query)
    for item in items:
        if normalize(str(item.get("name", ""))) == normalized_query:
            return item
        if normalize(str(item.get("ticker", ""))) == normalized_query:
            return item
    return None


def upsert_watchlist(name: str, ticker: str) -> tuple[str, dict[str, Any]]:
    items = load_watchlist()
    existing = find_item(items, name) or find_item(items, ticker)
    payload = {"name": name, "ticker": ticker}
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


def upsert_holding(name: str, ticker: str, quantity: int, average_price: float) -> tuple[str, dict[str, Any]]:
    items = load_holdings()
    existing = find_item(items, name) or find_item(items, ticker)
    payload = {
        "name": name,
        "ticker": ticker,
        "quantity": int(quantity),
        "average_price": float(average_price),
    }
    if existing:
        existing.update(payload)
        save_holdings(items)
        return "updated", existing

    items.append(payload)
    save_holdings(items)
    return "added", payload


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
