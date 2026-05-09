from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from config import GOOGLE_SERVICE_ACCOUNT_ENV_NAME, GOOGLE_SHEETS_SPREADSHEET_ID_ENV_NAME


LIST_FIELDS = {"themes", "subthemes", "non_priority_themes"}
INT_FIELDS = {"quantity", "remaining_quantity", "quant_score", "timing_score"}
FLOAT_FIELDS = {
    "avg_price",
    "price",
    "avg_price_before",
    "avg_price_after",
    "realized_profit",
    "realized_return_pct",
}

SHEET_HEADERS: dict[str, list[str]] = {
    "watchlist": ["name", "ticker", "themes", "subthemes", "non_priority_themes"],
    "holdings": ["name", "ticker", "quantity", "avg_price", "themes", "subthemes", "non_priority_themes"],
    "trade_history": [
        "date",
        "type",
        "name",
        "ticker",
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
        "action",
        "quant_score",
        "timing_score",
        "market_state",
        "themes",
        "memo",
    ],
}


def is_configured() -> bool:
    return bool(os.getenv(GOOGLE_SERVICE_ACCOUNT_ENV_NAME) and os.getenv(GOOGLE_SHEETS_SPREADSHEET_ID_ENV_NAME))


def _load_service_account_info() -> dict[str, Any]:
    raw = os.getenv(GOOGLE_SERVICE_ACCOUNT_ENV_NAME, "").strip()
    if not raw:
        raise RuntimeError(f"{GOOGLE_SERVICE_ACCOUNT_ENV_NAME} 환경변수가 없습니다.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{GOOGLE_SERVICE_ACCOUNT_ENV_NAME} JSON 파싱 실패: {exc}") from exc


@lru_cache(maxsize=1)
def _spreadsheet():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise RuntimeError("gspread/google-auth 패키지가 설치되어 있지 않습니다.") from exc

    spreadsheet_id = os.getenv(GOOGLE_SHEETS_SPREADSHEET_ID_ENV_NAME, "").strip()
    if not spreadsheet_id:
        raise RuntimeError(f"{GOOGLE_SHEETS_SPREADSHEET_ID_ENV_NAME} 환경변수가 없습니다.")

    credentials = Credentials.from_service_account_info(
        _load_service_account_info(),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(credentials)
    return client.open_by_key(spreadsheet_id)


def _worksheet(table_name: str):
    if table_name not in SHEET_HEADERS:
        raise ValueError(f"지원하지 않는 Google Sheets 테이블입니다: {table_name}")

    spreadsheet = _spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(table_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=table_name, rows=1000, cols=max(20, len(SHEET_HEADERS[table_name])))

    headers = SHEET_HEADERS[table_name]
    values = worksheet.get_all_values()
    if not values or values[0][:len(headers)] != headers:
        worksheet.update(values=[headers], range_name="A1")
    return worksheet


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [item.strip() for item in text.split(",") if item.strip()]


def _parse_value(field: str, value: Any) -> Any:
    if field in LIST_FIELDS:
        return _parse_list(value)
    if value is None or str(value).strip() == "":
        return None if field in FLOAT_FIELDS or field in INT_FIELDS else ""
    if field in INT_FIELDS:
        return int(float(value))
    if field in FLOAT_FIELDS:
        return float(value)
    return str(value)


def _format_value(field: str, value: Any) -> Any:
    if value is None:
        return ""
    if field in LIST_FIELDS:
        return json.dumps(value if isinstance(value, list) else _parse_list(value), ensure_ascii=False)
    return value


def load_records(table_name: str) -> list[dict[str, Any]]:
    headers = SHEET_HEADERS[table_name]
    worksheet = _worksheet(table_name)
    rows = worksheet.get_all_records(default_blank="")
    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {}
        empty = True
        for field in headers:
            value = _parse_value(field, row.get(field, ""))
            if value not in ("", [], None):
                empty = False
            record[field] = value
        if not empty:
            records.append(record)
    return records


def save_records(table_name: str, records: list[dict[str, Any]]) -> None:
    headers = SHEET_HEADERS[table_name]
    worksheet = _worksheet(table_name)
    values = [headers]
    for record in records:
        values.append([_format_value(field, record.get(field, "")) for field in headers])
    worksheet.clear()
    worksheet.update(values=values, range_name="A1")
