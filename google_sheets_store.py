from __future__ import annotations

import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import storage
from config import (
    ALERTS_FILE,
    HOLDINGS_FILE,
    RECOMMENDATION_HISTORY_FILE,
    TRADE_HISTORY_FILE,
    WATCHLIST_FILE,
)


Logger = Callable[[str], None] | None

GOOGLE_SHEET_ID_ENV = "GOOGLE_SHEET_ID"
GOOGLE_SERVICE_ACCOUNT_FILE_ENV = "GOOGLE_SERVICE_ACCOUNT_FILE"
SHEET_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
SHEET_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
THEME_UNIVERSE_FILE = "theme_universe.json"

SHEET_NAMES_BY_FILE = {
    HOLDINGS_FILE: "holdings",
    WATCHLIST_FILE: "watchlist",
    TRADE_HISTORY_FILE: "trade_history",
    RECOMMENDATION_HISTORY_FILE: "recommendation_history",
    ALERTS_FILE: "alerts",
    THEME_UNIVERSE_FILE: "theme_universe",
}

SCHEMAS = {
    "holdings": ["ticker", "name", "market", "quantity", "avg_price", "themes", "subthemes", "memo"],
    "watchlist": ["ticker", "name", "market", "themes", "subthemes", "memo"],
    "trade_history": [
        "date",
        "type",
        "ticker",
        "name",
        "market",
        "quantity",
        "price",
        "avg_price_before",
        "avg_price_after",
        "realized_profit",
        "realized_return_pct",
        "remaining_quantity",
        "memo",
    ],
    "recommendation_history": [
        "date",
        "name",
        "ticker",
        "market",
        "quant_score",
        "timing_score",
        "action",
        "entry_zone",
        "entry_low",
        "entry_high",
        "entry_reference_price",
        "stop_price",
        "target_1",
        "target_2",
        "target_final",
        "target_price",
        "confidence_score",
        "market_state",
        "themes",
        "subthemes",
        "prediction_result",
        "memo",
    ],
    "alerts": ["ticker", "name", "market", "alert_type", "condition", "target_price", "enabled", "memo"],
    "theme_universe": [
        "ticker",
        "name",
        "market",
        "themes",
        "subthemes",
        "benefit_type",
        "role",
        "priority",
        "status",
        "memo",
    ],
}

LIST_COLUMNS = {"themes", "subthemes"}
NUMERIC_COLUMNS = {
    "quantity",
    "avg_price",
    "price",
    "avg_price_before",
    "avg_price_after",
    "realized_profit",
    "realized_return_pct",
    "remaining_quantity",
    "quant_score",
    "timing_score",
    "entry_low",
    "entry_high",
    "entry_reference_price",
    "stop_price",
    "target_1",
    "target_2",
    "target_final",
    "target_price",
    "confidence_score",
    "theme_strength",
}
BOOL_COLUMNS = {"enabled", "entry_triggered", "hit_target_1", "hit_target_2", "hit_target_final", "hit_stop_loss"}
INT_COLUMNS = {"quantity", "remaining_quantity"}

_sheet_session: Any | None = None
_sheet_titles: set[str] | None = None
_last_loaded_rows_by_sheet: dict[str, list[dict[str, Any]]] = {}
_last_status_by_sheet: dict[str, dict[str, Any]] = {}


def _log(logger: Logger, message: str) -> None:
    storage.log(logger, message)


def _set_status(sheet_name: str, status: str, reason: str = "", rows: int = 0, fallback: bool = False) -> None:
    _last_status_by_sheet[sheet_name] = {
        "status": status,
        "reason": reason,
        "rows": rows,
        "fallback": fallback,
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def last_sheet_status(sheet_name: str) -> dict[str, Any]:
    return dict(_last_status_by_sheet.get(sheet_name, {"status": "not_run", "reason": "", "rows": 0, "fallback": False, "synced_at": ""}))


def last_theme_universe_sync_status() -> dict[str, Any]:
    return last_sheet_status("theme_universe")


def all_sheet_statuses() -> dict[str, dict[str, Any]]:
    return {sheet: last_sheet_status(sheet) for sheet in SHEET_NAMES_BY_FILE.values()}


def mark_sheet_fallback(sheet_name: str, reason: str, rows: int = 0) -> None:
    _set_status(sheet_name, "fallback_json", reason=reason, rows=rows, fallback=True)


def _google_sheet_id() -> str:
    return os.getenv(GOOGLE_SHEET_ID_ENV, "").strip()


def _google_service_account_file() -> str:
    return os.getenv(GOOGLE_SERVICE_ACCOUNT_FILE_ENV, "").strip()


def _configuration_error() -> str:
    missing: list[str] = []
    if not _google_sheet_id():
        missing.append(GOOGLE_SHEET_ID_ENV)
    if not _google_service_account_file():
        missing.append(GOOGLE_SERVICE_ACCOUNT_FILE_ENV)
    return ", ".join(missing)


def is_configured() -> bool:
    return not _configuration_error()


def _authorized_session(logger: Logger = None):
    global _sheet_session
    if _sheet_session is not None:
        return _sheet_session

    missing = _configuration_error()
    if missing:
        raise RuntimeError(f"환경변수 미설정: {missing}")

    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except Exception as exc:
        raise RuntimeError(f"Google 인증 라이브러리 로드 실패: {exc}") from exc

    service_account_file = Path(_google_service_account_file()).expanduser()
    try:
        credentials = service_account.Credentials.from_service_account_file(str(service_account_file), scopes=SHEET_SCOPES)
        _sheet_session = AuthorizedSession(credentials)
        return _sheet_session
    except Exception as exc:
        _log(logger, f"Google Sheets 서비스 계정 인증 실패: {exc}")
        raise


def _sheet_url(path: str) -> str:
    separator = "" if path.startswith(("?", ":")) else "/"
    return f"{SHEET_API_BASE}/{_google_sheet_id()}{separator}{path}"


def _sheet_range(sheet_name: str, cell_range: str = "A:ZZ") -> str:
    return quote(f"{sheet_name}!{cell_range}", safe="")


def _raise_for_sheet_response(response: Any) -> None:
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")


def check_connection(logger: Logger = None) -> bool:
    try:
        session = _authorized_session(logger=logger)
        response = session.get(_sheet_url("?fields=spreadsheetId"), timeout=20)
        _raise_for_sheet_response(response)
        return True
    except Exception as exc:
        _log(logger, f"Google Sheets 연결 확인 실패: {exc}")
        return False


def _load_sheet_titles(logger: Logger = None) -> set[str]:
    global _sheet_titles
    if _sheet_titles is not None:
        return _sheet_titles
    session = _authorized_session(logger=logger)
    response = session.get(_sheet_url("?fields=sheets.properties.title"), timeout=20)
    _raise_for_sheet_response(response)
    payload = response.json()
    _sheet_titles = {
        str(sheet.get("properties", {}).get("title", ""))
        for sheet in payload.get("sheets", [])
        if sheet.get("properties", {}).get("title")
    }
    return _sheet_titles


def _ensure_sheet_exists(sheet_name: str, logger: Logger = None) -> None:
    global _sheet_titles
    titles = _load_sheet_titles(logger=logger)
    if sheet_name in titles:
        return
    session = _authorized_session(logger=logger)
    body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
    response = session.post(_sheet_url(":batchUpdate"), json=body, timeout=20)
    _raise_for_sheet_response(response)
    _sheet_titles = set(titles)
    _sheet_titles.add(sheet_name)
    _log(logger, f"Google Sheets 탭 생성: {sheet_name}")


def _split_csv_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def infer_market(ticker: Any) -> str:
    normalized = _normalize_ticker(ticker)
    if normalized.endswith(".KS"):
        return "KOSPI"
    if normalized.endswith(".KQ"):
        return "KOSDAQ"
    if normalized:
        return "NASDAQ"
    return ""


def _parse_number(value: Any, integer: bool = False) -> int | float | str:
    text = str(value or "").strip()
    if text == "":
        return ""
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return text
    if integer or number.is_integer():
        return int(number)
    return number


def _parse_bool(value: Any) -> bool | str:
    text = str(value or "").strip()
    if text == "":
        return ""
    if text.lower() in {"1", "true", "yes", "y", "on", "활성", "사용"}:
        return True
    if text.lower() in {"0", "false", "no", "n", "off", "비활성", "중지"}:
        return False
    return text


def _parse_cell(header: str, value: Any) -> Any:
    if header in LIST_COLUMNS:
        return _split_csv_list(value)
    if header in BOOL_COLUMNS:
        return _parse_bool(value)
    if header in NUMERIC_COLUMNS:
        return _parse_number(value, integer=header in INT_COLUMNS)
    return str(value or "").strip()


def _format_cell(header: str, value: Any) -> Any:
    if value is None:
        return ""
    if header in LIST_COLUMNS:
        return ", ".join(_split_csv_list(value))
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def _headers_for_items(sheet_name: str, items: list[dict[str, Any]]) -> list[str]:
    headers = list(SCHEMAS[sheet_name])
    for item in items:
        for key in item.keys():
            if key not in headers:
                headers.append(key)
    return headers


def _normalize_item(sheet_name: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    if "ticker" in SCHEMAS[sheet_name]:
        normalized["ticker"] = _normalize_ticker(normalized.get("ticker"))
    if "market" in SCHEMAS[sheet_name] and not str(normalized.get("market", "")).strip():
        normalized["market"] = infer_market(normalized.get("ticker"))
    if sheet_name == "trade_history" and "type" not in normalized and "action" in normalized:
        normalized["type"] = normalized.get("action", "")
    if sheet_name == "alerts":
        if "target_price" not in normalized and "price" in normalized:
            normalized["target_price"] = normalized.get("price")
        if "price" not in normalized and "target_price" in normalized:
            normalized["price"] = normalized.get("target_price")
        if "enabled" not in normalized:
            normalized["enabled"] = True
    if sheet_name == "theme_universe" and not str(normalized.get("status", "")).strip():
        normalized["status"] = "active"
    return normalized


def _items_from_values(sheet_name: str, values: list[list[Any]]) -> list[dict[str, Any]]:
    if not values:
        return []
    headers = [str(header).strip() for header in values[0]]
    items: list[dict[str, Any]] = []
    for row in values[1:]:
        if not any(str(value).strip() for value in row):
            continue
        item: dict[str, Any] = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            value = row[index] if index < len(row) else ""
            parsed = _parse_cell(header, value)
            if parsed == "" or parsed == []:
                continue
            item[header] = parsed
        item = _normalize_item(sheet_name, item)
        if "ticker" in SCHEMAS[sheet_name] and not item.get("ticker"):
            continue
        if "status" in SCHEMAS[sheet_name] and str(item.get("status", "")).strip().lower() != "active":
            continue
        items.append(item)
    return items


def _values_from_items(sheet_name: str, items: list[dict[str, Any]]) -> list[list[Any]]:
    normalized_items = [_normalize_item(sheet_name, item) for item in items if isinstance(item, dict)]
    headers = _headers_for_items(sheet_name, normalized_items)
    rows = [headers]
    for item in normalized_items:
        rows.append([_format_cell(header, item.get(header, "")) for header in headers])
    return rows


def _load_items_from_sheet(sheet_name: str, logger: Logger = None) -> list[dict[str, Any]] | None:
    if sheet_name not in SCHEMAS:
        _set_status(sheet_name, "failed", reason="unknown_sheet", fallback=True)
        return None
    try:
        session = _authorized_session(logger=logger)
        response = session.get(_sheet_url(f"values/{_sheet_range(sheet_name)}"), timeout=20)
        _raise_for_sheet_response(response)
        values = response.json().get("values", [])
        items = _items_from_values(sheet_name, values)
        _last_loaded_rows_by_sheet[sheet_name] = items
        _set_status(sheet_name, "loaded", rows=len(items))
        _log(logger, f"{sheet_name} Sheets 로드 성공: {len(items)}개")
        return items
    except Exception as exc:
        _set_status(sheet_name, "failed", reason=str(exc), fallback=True)
        _log(logger, f"{sheet_name} Sheets 로드 실패: {exc}. 기존 JSON으로 진행합니다.")
        return None


def load_items_from_sheet_for_file(file_name: str, logger: Logger = None) -> list[dict[str, Any]] | None:
    sheet_name = SHEET_NAMES_BY_FILE.get(file_name)
    if not sheet_name:
        return None
    return _load_items_from_sheet(sheet_name, logger=logger)


def _existing_sheet_data_count(sheet_name: str, logger: Logger = None) -> int:
    session = _authorized_session(logger=logger)
    response = session.get(_sheet_url(f"values/{_sheet_range(sheet_name)}"), timeout=20)
    _raise_for_sheet_response(response)
    values = response.json().get("values", [])
    return max(0, len([row for row in values[1:] if any(str(value).strip() for value in row)]))


def _save_items_to_sheet(sheet_name: str, items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    if sheet_name not in SCHEMAS:
        _set_status(sheet_name, "failed", reason="unknown_sheet", fallback=True)
        return False
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        _set_status(sheet_name, "failed", reason="items must be list[dict]", fallback=True)
        _log(logger, f"{sheet_name} Sheets 저장 스킵: 목록/객체 행 형식이 아닙니다.")
        return False
    try:
        _ensure_sheet_exists(sheet_name, logger=logger)
        if not items and not clear:
            existing_count = _existing_sheet_data_count(sheet_name, logger=logger)
            if existing_count:
                reason = f"빈 목록 저장 차단: 기존 sheet 데이터 {existing_count}개"
                _set_status(sheet_name, "blocked_empty_write", reason=reason, rows=existing_count, fallback=True)
                _log(logger, f"{sheet_name} Sheets 저장 스킵: {reason}. 명시적 clear=True일 때만 비울 수 있습니다.")
                return False

        session = _authorized_session(logger=logger)
        clear_url = _sheet_url(f"values/{_sheet_range(sheet_name)}:clear")
        response = session.post(clear_url, json={}, timeout=20)
        _raise_for_sheet_response(response)
        update_url = _sheet_url(f"values/{_sheet_range(sheet_name)}?valueInputOption=RAW")
        response = session.put(update_url, json={"values": _values_from_items(sheet_name, items)}, timeout=20)
        _raise_for_sheet_response(response)
        _last_loaded_rows_by_sheet[sheet_name] = [_normalize_item(sheet_name, item) for item in items]
        _set_status(sheet_name, "saved", rows=len(items))
        _log(logger, f"{sheet_name} Sheets 저장 성공: {len(items)}개")
        return True
    except Exception as exc:
        _set_status(sheet_name, "failed", reason=str(exc), fallback=True)
        _log(logger, f"{sheet_name} Sheets 저장 실패: {exc}")
        return False


def save_items_to_sheet_for_file(file_name: str, items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    sheet_name = SHEET_NAMES_BY_FILE.get(file_name)
    if not sheet_name:
        return False
    saved = _save_items_to_sheet(sheet_name, items, logger=logger, clear=clear)
    return saved


def _save_cache_for_file(file_name: str, items: Any, logger: Logger = None) -> None:
    try:
        storage._save_local_json_file(file_name, items, logger=logger)
    except Exception as exc:
        _log(logger, f"{file_name} JSON 캐시 갱신 실패: {exc}")


def _save_to_sheet_and_cache(file_name: str, items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    sheet_name = SHEET_NAMES_BY_FILE[file_name]
    normalized_items = [_normalize_item(sheet_name, item) for item in items if isinstance(item, dict)]
    saved = save_items_to_sheet_for_file(file_name, items, logger=logger, clear=clear)
    if saved:
        _save_cache_for_file(file_name, normalized_items, logger=logger)
    return saved


def load_holdings_from_sheet(logger: Logger = None) -> list[dict[str, Any]]:
    return _load_items_from_sheet("holdings", logger=logger) or []


def save_holdings_to_sheet(items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    return _save_to_sheet_and_cache(HOLDINGS_FILE, items, logger=logger, clear=clear)


def load_watchlist_from_sheet(logger: Logger = None) -> list[dict[str, Any]]:
    return _load_items_from_sheet("watchlist", logger=logger) or []


def save_watchlist_to_sheet(items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    return _save_to_sheet_and_cache(WATCHLIST_FILE, items, logger=logger, clear=clear)


def load_trade_history_from_sheet(logger: Logger = None) -> list[dict[str, Any]]:
    return _load_items_from_sheet("trade_history", logger=logger) or []


def save_trade_history_to_sheet(items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    return _save_to_sheet_and_cache(TRADE_HISTORY_FILE, items, logger=logger, clear=clear)


def load_recommendation_history_from_sheet(logger: Logger = None) -> list[dict[str, Any]]:
    return _load_items_from_sheet("recommendation_history", logger=logger) or []


def save_recommendation_history_to_sheet(items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    return _save_to_sheet_and_cache(RECOMMENDATION_HISTORY_FILE, items, logger=logger, clear=clear)


def load_alerts_from_sheet(logger: Logger = None) -> list[dict[str, Any]]:
    return _load_items_from_sheet("alerts", logger=logger) or []


def save_alerts_to_sheet(items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    return _save_to_sheet_and_cache(ALERTS_FILE, items, logger=logger, clear=clear)


def load_theme_universe_from_sheet(logger: Logger = None) -> list[dict[str, Any]]:
    return _load_items_from_sheet("theme_universe", logger=logger) or []


def _theme_universe_cache_from_rows(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    universe: dict[str, list[str]] = {}
    seen_by_theme: dict[str, set[str]] = {}
    for row in rows:
        ticker = _normalize_ticker(row.get("ticker"))
        if not ticker:
            continue
        for theme in _split_csv_list(row.get("themes")):
            seen = seen_by_theme.setdefault(theme, set())
            if ticker in seen:
                continue
            universe.setdefault(theme, []).append(ticker)
            seen.add(ticker)
    return universe


def save_theme_universe_to_sheet(items: list[dict[str, Any]], logger: Logger = None, *, clear: bool = False) -> bool:
    saved = _save_items_to_sheet("theme_universe", items, logger=logger, clear=clear)
    if saved:
        _save_cache_for_file(THEME_UNIVERSE_FILE, _theme_universe_cache_from_rows(items), logger=logger)
    return saved


def sync_theme_universe_from_sheet(logger: Logger = None) -> dict[str, list[str]]:
    rows = _load_items_from_sheet("theme_universe", logger=logger)
    if rows is None:
        payload = storage.load_json_file(THEME_UNIVERSE_FILE, {}, logger=logger)
        return payload if isinstance(payload, dict) else {}
    if not rows:
        payload = storage.load_json_file(THEME_UNIVERSE_FILE, {}, logger=logger)
        if isinstance(payload, dict) and payload:
            _set_status("theme_universe", "fallback_json", reason="sheet is empty", rows=len(payload), fallback=True)
            _log(logger, "theme_universe Sheets가 비어 있어 기존 JSON 캐시를 사용합니다.")
            return payload
    universe = _theme_universe_cache_from_rows(rows)
    _save_cache_for_file(THEME_UNIVERSE_FILE, universe, logger=logger)
    _set_status("theme_universe", "synced", rows=len(rows), fallback=False)
    _log(logger, f"theme_universe Sheets → JSON 동기화 완료: active {len(rows)}개 / 테마 {len(universe)}개")
    return universe


def migrate_json_to_sheets(logger: Logger = None, *, dry_run: bool = True, clear: bool = False) -> dict[str, str]:
    results: dict[str, str] = {}
    for file_name, sheet_name in SHEET_NAMES_BY_FILE.items():
        if file_name == THEME_UNIVERSE_FILE:
            payload = storage.load_json_file(file_name, {}, logger=logger)
            items = [
                {"ticker": ticker, "themes": [theme], "status": "active", "market": infer_market(ticker)}
                for theme, tickers in (payload.items() if isinstance(payload, dict) else [])
                for ticker in (tickers if isinstance(tickers, list) else [])
            ]
        else:
            payload = storage._load_local_json_file(file_name, [], logger=logger)
            items = payload if isinstance(payload, list) else []

        existing = _load_items_from_sheet(sheet_name, logger=logger)
        existing_count = len(existing or [])
        if existing_count:
            _log(logger, f"{sheet_name} 탭에 기존 데이터 {existing_count}개가 있습니다. 업로드 시 덮어씁니다.")
        if dry_run:
            results[sheet_name] = f"dry_run:{len(items)}"
            continue
        results[sheet_name] = "uploaded" if _save_items_to_sheet(sheet_name, items, logger=logger, clear=clear) else "failed"
    return results


def theme_universe_summary(logger: Logger = None) -> dict[str, Any]:
    rows = _last_loaded_rows_by_sheet.get("theme_universe")
    if rows is None and is_configured():
        rows = load_theme_universe_from_sheet(logger=logger)

    if rows:
        tickers = {_normalize_ticker(row.get("ticker")) for row in rows if _normalize_ticker(row.get("ticker"))}
        market_counts = Counter(str(row.get("market", "") or "미분류").strip() for row in rows)
        theme_counts = Counter(theme for row in rows for theme in _split_csv_list(row.get("themes")) if theme)
        return {
            "total_tickers": len(tickers),
            "market_counts": dict(market_counts),
            "theme_counts": dict(theme_counts.most_common(10)),
            "sync_status": last_theme_universe_sync_status(),
            "source": "sheet",
        }

    universe = storage.load_json_file(THEME_UNIVERSE_FILE, {}, logger=logger)
    if not isinstance(universe, dict):
        universe = {}
    tickers = {
        _normalize_ticker(ticker)
        for tickers_for_theme in universe.values()
        if isinstance(tickers_for_theme, list)
        for ticker in tickers_for_theme
        if _normalize_ticker(ticker)
    }
    theme_counts = {
        str(theme): len(tickers_for_theme)
        for theme, tickers_for_theme in universe.items()
        if isinstance(tickers_for_theme, list)
    }
    return {
        "total_tickers": len(tickers),
        "market_counts": {},
        "theme_counts": dict(sorted(theme_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
        "sync_status": last_theme_universe_sync_status(),
        "source": "json_cache",
    }


def data_status(logger: Logger = None) -> dict[str, Any]:
    connected = check_connection(logger=logger) if is_configured() else False
    counts = {
        "holdings": len(storage.load_holdings(logger=logger)),
        "watchlist": len(storage.load_watchlist(logger=logger)),
        "recommendation_history": len(storage.load_recommendation_history(logger=logger)),
        "trade_history": len(storage.load_trade_history(logger=logger)),
        "alerts": len(storage.load_alerts(logger=logger)),
    }
    theme_summary = theme_universe_summary(logger=logger)
    counts["theme_universe"] = int(theme_summary.get("total_tickers", 0) or 0)
    statuses = all_sheet_statuses()
    return {
        "connected": connected,
        "configured": is_configured(),
        "counts": counts,
        "fallback_used": any(status.get("fallback") for status in statuses.values()),
        "statuses": statuses,
    }
