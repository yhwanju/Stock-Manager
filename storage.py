from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

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


PROJECT_ROOT = Path(__file__).resolve(strict=True).parent
DATA_DIR = (PROJECT_ROOT / "data").resolve()
LOG_DIR = (PROJECT_ROOT / "logs").resolve()
BACKUP_DIR = (PROJECT_ROOT / "backups").resolve()
BASE_DIR = DATA_DIR
Logger = Callable[[str], None] | None
BACKUP_RETENTION_DAYS = 30
_last_backup_date: str | None = None
_backup_in_progress = False
DATA_FILES = {
    ALERTS_FILE,
    HOLDINGS_FILE,
    RECOMMENDATION_HISTORY_FILE,
    TRADE_HISTORY_FILE,
    WATCHLIST_FILE,
}
SHEET_SYNC_FILES = {
    ALERTS_FILE: "alerts",
    HOLDINGS_FILE: "holdings",
    RECOMMENDATION_HISTORY_FILE: "recommendation_history",
    TRADE_HISTORY_FILE: "trade_history",
    WATCHLIST_FILE: "watchlist",
}
SHEET_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
SHEET_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
GOOGLE_SHEET_ID_ENV = "GOOGLE_SHEET_ID"
GOOGLE_SERVICE_ACCOUNT_JSON_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
GOOGLE_SERVICE_ACCOUNT_FILE_ENV = "GOOGLE_SERVICE_ACCOUNT_FILE"
DEFAULT_GOOGLE_SHEET_ID = "103QZu66G5eONaBLPjBMZ8FoNpLkTnSHXwyjVd_Neq8A"
PREFERRED_SHEET_HEADERS = {
    HOLDINGS_FILE: ["name", "ticker", "quantity", "avg_price", "themes", "subthemes"],
    WATCHLIST_FILE: ["name", "ticker", "themes", "subthemes"],
    TRADE_HISTORY_FILE: ["date", "name", "ticker", "action", "quantity", "price", "memo"],
    RECOMMENDATION_HISTORY_FILE: [
        "recommendation_id",
        "date",
        "name",
        "ticker",
        "price",
        "entry_low",
        "entry_high",
        "entry_reference_price",
        "entry_zone",
        "action",
        "quant_score",
        "timing_score",
        "market_state",
        "theme_strength",
        "confidence_score",
        "predicted_best_target",
        "actual_best_target",
        "target_1",
        "target_2",
        "target_final",
        "target_price",
        "stop_price",
        "entry_triggered",
        "entry_triggered_at",
        "hit_target_1",
        "hit_target_2",
        "hit_target_final",
        "hit_stop_loss",
        "prediction_result",
        "themes",
        "memo",
    ],
    ALERTS_FILE: ["name", "ticker", "condition", "price", "created_at", "memo"],
}
THEME_UNIVERSE_FILE = "theme_universe.json"
UNCLASSIFIED_THEME = "미분류"
_sheet_session: Any | None = None
_sheet_titles: set[str] | None = None
_sheet_write_failed_files: set[str] = set()


def describe_payload(payload: Any) -> str:
    if isinstance(payload, list):
        return f"{len(payload)}개 항목"
    if isinstance(payload, dict):
        return f"{len(payload)}개 키"
    return type(payload).__name__


def log(logger: Logger, message: str) -> None:
    write_storage_log(message)
    if logger:
        logger(message)


def write_storage_log(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (LOG_DIR / "storage.log").open("a", encoding="utf-8") as file:
            file.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def json_file_path(file_name: str) -> Path:
    if file_name in DATA_FILES:
        return (DATA_DIR / file_name).resolve()
    return (PROJECT_ROOT / file_name).resolve()


def json_file_path_text(file_name: str) -> str:
    return str(json_file_path(file_name))


def storage_location_text(file_name: str) -> str:
    return str(json_file_path(file_name))


def legacy_json_file_path(file_name: str) -> Path:
    return (PROJECT_ROOT / file_name).resolve()


def backup_file_path(file_name: str) -> Path:
    path = json_file_path(file_name)
    return path.with_suffix(path.suffix + ".bak")


def restore_backup_file(file_name: str, logger: Logger = None) -> bool:
    path = json_file_path(file_name)
    backup_path = backup_file_path(file_name)
    if not backup_path.exists():
        log(logger, f"{file_name} 롤백 실패: 백업 파일이 없습니다. 경로: {backup_path}")
        return False
    shutil.copy2(backup_path, path)
    log(logger, f"{file_name} 롤백 완료: {backup_path} -> {path}")
    return True


def prune_old_backups(logger: Logger = None) -> None:
    if not BACKUP_DIR.exists():
        return
    backup_dirs = sorted([path for path in BACKUP_DIR.iterdir() if path.is_dir()])
    for old_dir in backup_dirs[:-BACKUP_RETENTION_DAYS]:
        shutil.rmtree(old_dir, ignore_errors=True)
        log(logger, f"오래된 백업 삭제: {old_dir}")


def run_daily_backup_if_due(logger: Logger = None, *, force: bool = False) -> None:
    global _backup_in_progress, _last_backup_date
    if _backup_in_progress:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if not force and _last_backup_date == today:
        return

    _backup_in_progress = True
    try:
        target_dir = BACKUP_DIR / today
        target_dir.mkdir(parents=True, exist_ok=True)
        for source_dir_name in ("data", "logs"):
            source_dir = PROJECT_ROOT / source_dir_name
            if not source_dir.exists():
                continue
            dest_dir = target_dir / source_dir_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            for source in source_dir.glob("*"):
                if source.is_file():
                    shutil.copy2(source, dest_dir / source.name)
        prune_old_backups(logger=logger)
        _last_backup_date = today
        log(logger, f"일일 백업 완료: {target_dir}")
    finally:
        _backup_in_progress = False


def _load_json_from_path(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _load_local_json_file(file_name: str, default: Any, *, required: bool = False, logger: Logger = None) -> Any:
    path = json_file_path(file_name)
    log(logger, f"{file_name} 읽기 파일 경로: {path}")
    if not path.exists():
        legacy_path = legacy_json_file_path(file_name)
        if file_name in DATA_FILES and legacy_path.exists():
            try:
                payload = _load_json_from_path(legacy_path)
                save_json_file(file_name, payload, logger=logger)
                log(logger, f"{file_name} data 폴더 초기 이전 성공: {legacy_path} -> {path}")
                return payload
            except Exception as exc:
                log(logger, f"{file_name} data 폴더 초기 이전 실패: {exc}. 기본값으로 진행합니다.")

        level = "필수" if required else "선택"
        log(logger, f"{file_name} 로드 실패: {level} 파일이 없습니다. 경로: {path}")
        return default

    try:
        payload = _load_json_from_path(path)
    except json.JSONDecodeError as exc:
        if file_name in DATA_FILES and restore_backup_file(file_name, logger=logger):
            try:
                payload = _load_json_from_path(path)
                log(logger, f"{file_name} JSON 깨짐 감지 후 .bak 자동 복구 성공: {path}")
                return payload
            except Exception as restore_exc:
                log(logger, f"{file_name} .bak 자동 복구 후 재로드 실패: {restore_exc}")
        log(logger, f"{file_name} 로드 실패: JSON 파싱 오류 - {exc}. 경로: {path}")
        return default

    log(logger, f"{file_name} 로드 성공: {describe_payload(payload)} / 경로: {path}")
    return payload


def load_json_file(file_name: str, default: Any, *, required: bool = False, logger: Logger = None) -> Any:
    if file_name in SHEET_SYNC_FILES and file_name not in _sheet_write_failed_files:
        payload = _load_sheet_json_file(file_name, logger=logger)
        if payload is not None:
            _save_local_json_file(file_name, payload, logger=logger)
            log(logger, f"{file_name} Sheets → JSON 동기화 완료: {describe_payload(payload)}")
            return payload
    return _load_local_json_file(file_name, default, required=required, logger=logger)


def _save_local_json_file(file_name: str, payload: Any, logger: Logger = None) -> None:
    run_daily_backup_if_due(logger=logger)
    path = json_file_path(file_name)
    log(logger, f"{file_name} 저장 파일 경로: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file_path(file_name)
    has_backup = False
    if path.exists():
        shutil.copy2(path, backup_path)
        has_backup = True
        log(logger, f"{file_name} 백업 생성: {backup_path}")

    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temp_path.replace(path)

        verified_payload = _load_json_from_path(path)
        if verified_payload != payload:
            raise IOError(f"{file_name} 저장 검증 실패: 저장 후 다시 읽은 내용이 다릅니다. 경로: {path}")
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink()
        if has_backup:
            restore_backup_file(file_name, logger=logger)
            log(logger, f"{file_name} 저장 실패 후 rollback 완료: {exc}")
        else:
            log(logger, f"{file_name} 저장 실패: rollback 가능한 .bak 없음 - {exc}")
        raise

    log(logger, f"{file_name} 저장 성공: {describe_payload(payload)} / 경로: {path}")


def save_json_file(file_name: str, payload: Any, logger: Logger = None) -> None:
    _save_local_json_file(file_name, payload, logger=logger)
    if file_name not in SHEET_SYNC_FILES:
        return
    if _save_sheet_json_file(file_name, payload, logger=logger):
        _sheet_write_failed_files.discard(file_name)
        return
    _sheet_write_failed_files.add(file_name)
    log(logger, f"{file_name} Sheets 저장 실패: 로컬 JSON 저장은 유지합니다.")


def _google_sheet_id() -> str:
    return os.getenv(GOOGLE_SHEET_ID_ENV, "").strip() or DEFAULT_GOOGLE_SHEET_ID


def _google_service_account_info(logger: Logger = None) -> dict[str, Any] | None:
    raw = os.getenv(GOOGLE_SERVICE_ACCOUNT_JSON_ENV, "").strip()
    if not raw:
        raw = os.getenv(GOOGLE_SERVICE_ACCOUNT_FILE_ENV, "").strip()
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        if not raw:
            return None
        with Path(raw).expanduser().open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:
        log(logger, f"{GOOGLE_SERVICE_ACCOUNT_JSON_ENV} 파싱 실패: {exc}")
        return None


def _sheet_sync_configured(logger: Logger = None) -> bool:
    if not _google_sheet_id():
        return False
    if not (
        os.getenv(GOOGLE_SERVICE_ACCOUNT_JSON_ENV, "").strip()
        or os.getenv(GOOGLE_SERVICE_ACCOUNT_FILE_ENV, "").strip()
    ):
        return False
    return True


def _sheet_authorized_session(logger: Logger = None):
    global _sheet_session
    if _sheet_session is not None:
        return _sheet_session
    if not _sheet_sync_configured(logger=logger):
        return None
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except Exception as exc:
        log(logger, f"Google Sheets 인증 라이브러리 로드 실패: {exc}")
        return None

    info = _google_service_account_info(logger=logger)
    if not info:
        return None
    try:
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SHEET_SCOPES)
        _sheet_session = AuthorizedSession(credentials)
        return _sheet_session
    except Exception as exc:
        log(logger, f"Google Sheets 인증 실패: {exc}")
        return None


def _sheet_url(path: str) -> str:
    separator = "" if path.startswith(("?", ":")) else "/"
    return f"{SHEET_API_BASE}/{_google_sheet_id()}{separator}{path}"


def _raise_for_sheet_response(response: Any) -> None:
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")


def _load_sheet_titles(logger: Logger = None) -> set[str]:
    global _sheet_titles
    if _sheet_titles is not None:
        return _sheet_titles
    session = _sheet_authorized_session(logger=logger)
    if session is None:
        return set()
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
    session = _sheet_authorized_session(logger=logger)
    if session is None:
        raise RuntimeError("Google Sheets 인증 세션이 없습니다.")
    body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
    response = session.post(_sheet_url(":batchUpdate"), json=body, timeout=20)
    _raise_for_sheet_response(response)
    _sheet_titles = set(titles)
    _sheet_titles.add(sheet_name)
    log(logger, f"Google Sheets 탭 생성: {sheet_name}")


def _sheet_range(sheet_name: str, cell_range: str = "A:ZZ") -> str:
    return quote(f"{sheet_name}!{cell_range}", safe="")


def _sheet_cell_from_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def _sheet_headers(file_name: str, items: list[dict[str, Any]]) -> list[str]:
    headers: list[str] = []
    for header in PREFERRED_SHEET_HEADERS.get(file_name, []):
        if header not in headers:
            headers.append(header)
    for item in items:
        for key in item.keys():
            if key not in headers:
                headers.append(key)
    return headers


def _sheet_rows_from_items(file_name: str, items: list[dict[str, Any]]) -> list[list[Any]]:
    headers = _sheet_headers(file_name, items)
    rows = [headers]
    for item in items:
        rows.append([_sheet_cell_from_value(item.get(header, "")) for header in headers])
    return rows


def _parse_sheet_cell(header: str, value: Any) -> Any:
    if value is None:
        return ""
    text = str(value).strip()
    if text == "":
        return ""
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "null":
        return None
    if text.startswith(("[", "{")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    if _looks_numeric_header(header):
        try:
            number = float(text.replace(",", ""))
        except ValueError:
            return value
        return int(number) if number.is_integer() else number
    return value


def _looks_numeric_header(header: str) -> bool:
    normalized = header.lower()
    numeric_names = {
        "quantity",
        "avg_price",
        "average_price",
        "price",
        "entry_low",
        "entry_high",
        "entry_reference_price",
        "quant_score",
        "timing_score",
        "theme_strength",
        "confidence_score",
        "target_1",
        "target_2",
        "target_final",
        "target_price",
        "stop_price",
        "return_pct",
    }
    return (
        normalized in numeric_names
        or normalized.endswith("_price")
        or normalized.endswith("_score")
        or normalized.endswith("_pct")
    )


def _items_from_sheet_rows(values: list[list[Any]]) -> list[dict[str, Any]]:
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
            if str(value).strip() == "":
                continue
            item[header] = _parse_sheet_cell(header, value)
        items.append(item)
    return items


def _load_sheet_json_file(file_name: str, logger: Logger = None) -> list[dict[str, Any]] | None:
    try:
        import google_sheets_store

        payload = google_sheets_store.load_items_from_sheet_for_file(file_name, logger=logger)
        if payload is None:
            return None
        if not payload:
            local_payload = _load_local_json_file(file_name, [], logger=logger)
            if isinstance(local_payload, list) and local_payload:
                sheet_name = SHEET_SYNC_FILES.get(file_name, file_name)
                google_sheets_store.mark_sheet_fallback(sheet_name, "sheet is empty; local JSON has data", rows=len(local_payload))
                log(logger, f"{file_name} Sheets가 비어 있어 기존 JSON 캐시를 사용합니다.")
                return None
        return payload
    except Exception as exc:
        log(logger, f"{file_name} Sheets 로드 실패: {exc}. 기존 JSON으로 진행합니다.")
        return None


def _save_sheet_json_file(file_name: str, payload: Any, logger: Logger = None) -> bool:
    try:
        import google_sheets_store

        if not isinstance(payload, list):
            log(logger, f"{file_name} Sheets 저장 스킵: 목록 형식이 아닙니다.")
            return False
        return google_sheets_store.save_items_to_sheet_for_file(file_name, payload, logger=logger)
    except Exception as exc:
        log(logger, f"{file_name} Sheets 저장 실패: {exc}")
        return False


def sync_sheets_to_json(logger: Logger = None) -> dict[str, str]:
    results: dict[str, str] = {}
    for file_name in SHEET_SYNC_FILES:
        payload = _load_sheet_json_file(file_name, logger=logger)
        if payload is None:
            results[file_name] = "fallback_json"
            continue
        _save_local_json_file(file_name, payload, logger=logger)
        _sheet_write_failed_files.discard(file_name)
        results[file_name] = "synced"
    return results


def migrate_json_to_sheets(logger: Logger = None, *, dry_run: bool = True, clear: bool = False) -> dict[str, str]:
    import google_sheets_store

    return google_sheets_store.migrate_json_to_sheets(logger=logger, dry_run=dry_run, clear=clear)


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
    path = json_file_path(HOLDINGS_FILE)
    log(logger, f"holdings 읽기 경로 확인: {path}")
    payload = load_json_file(HOLDINGS_FILE, [], required=True, logger=logger)
    if not isinstance(payload, list):
        raise IOError(f"holdings 로드 실패: 목록 형식이 아닙니다. 경로: {path}")
    log(logger, f"holdings 읽기 완료: {len(payload)}개 / 경로: {storage_location_text(HOLDINGS_FILE)}")
    return payload


def save_holdings(
    items: list[dict[str, Any]],
    logger: Logger = None,
    *,
    previous_count: int | None = None,
    min_expected_count: int | None = None,
) -> None:
    path = json_file_path(HOLDINGS_FILE)
    log(logger, f"holdings 저장 시작: {len(items)}개 / 경로: {path}")
    if previous_count is not None:
        log(logger, f"기존 holdings: {previous_count}개")
    save_json_file(HOLDINGS_FILE, items, logger=logger)
    verified = _load_local_json_file(HOLDINGS_FILE, [], required=True, logger=logger)
    if not isinstance(verified, list):
        restore_backup_file(HOLDINGS_FILE, logger=logger)
        raise IOError(f"holdings 저장 검증 실패: 다시 읽은 데이터가 목록 형식이 아닙니다. 경로: {path}")
    log(logger, f"holdings 저장 후 재읽기 완료: {len(verified)}개 / 경로: {path}")
    if min_expected_count is not None and len(verified) < min_expected_count:
        restore_backup_file(HOLDINGS_FILE, logger=logger)
        raise IOError(
            f"holdings 저장 검증 실패: 저장 후 종목 수가 비정상 감소했습니다. "
            f"기대 최소 {min_expected_count}개, 실제 {len(verified)}개 / 경로: {path}"
        )
    if verified != items:
        restore_backup_file(HOLDINGS_FILE, logger=logger)
        raise IOError(f"holdings 저장 검증 실패: 저장 요청 데이터와 재읽기 데이터가 다릅니다. 경로: {path}")
    log(logger, f"holdings 저장 검증 성공: {len(verified)}개 / 경로: {path}")


def _theme_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            stripped = str(item).strip()
            if stripped:
                values.append(stripped)
        return values
    stripped = str(value).strip()
    return [stripped] if stripped else []


def is_unclassified_theme(value: Any) -> bool:
    values = _theme_values(value)
    if not values:
        return True
    return all(theme == UNCLASSIFIED_THEME for theme in values)


def _ticker_lookup_keys(ticker: Any) -> list[str]:
    key = str(ticker or "").strip().upper()
    if not key:
        return []
    keys = [key]
    if "." in key:
        base_key = key.split(".", 1)[0]
        if base_key and base_key not in keys:
            keys.append(base_key)
    return keys


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _theme_universe_ticker_index(logger: Logger = None) -> dict[str, list[str]]:
    payload = load_json_file(THEME_UNIVERSE_FILE, {}, logger=logger)
    if not isinstance(payload, dict):
        log(logger, f"{THEME_UNIVERSE_FILE} 로드 실패: 객체 형식이 아닙니다.")
        return {}

    ticker_theme_index: dict[str, list[str]] = {}
    for theme, tickers in payload.items():
        theme_name = str(theme).strip()
        if not theme_name:
            continue

        if isinstance(tickers, str):
            ticker_values = [tickers]
        elif isinstance(tickers, list):
            ticker_values = tickers
        else:
            continue

        for ticker in ticker_values:
            for key in _ticker_lookup_keys(ticker):
                themes = ticker_theme_index.setdefault(key, [])
                _append_unique(themes, theme_name)
    return ticker_theme_index


def _item_allows_theme_patch(item: dict[str, Any]) -> bool:
    return is_unclassified_theme(item.get("themes")) and is_unclassified_theme(item.get("theme"))


def _display_theme_value(item: dict[str, Any]) -> str:
    themes = _theme_values(item.get("themes"))
    if themes:
        return ", ".join(themes)
    theme = _theme_values(item.get("theme"))
    if theme:
        return ", ".join(theme)
    return UNCLASSIFIED_THEME


def _themes_for_ticker(ticker: Any, ticker_theme_index: dict[str, list[str]]) -> list[str]:
    themes: list[str] = []
    for key in _ticker_lookup_keys(ticker):
        for theme in ticker_theme_index.get(key, []):
            _append_unique(themes, theme)
    return themes


def _patch_item_themes(
    items: list[dict[str, Any]],
    ticker_theme_index: dict[str, list[str]],
    logger: Logger = None,
) -> int:
    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue

        ticker = str(item.get("ticker", "")).strip()
        themes = _themes_for_ticker(ticker, ticker_theme_index)
        if not ticker or not themes or not _item_allows_theme_patch(item):
            continue

        before = _display_theme_value(item)
        item["themes"] = themes
        if "theme" in item:
            item["theme"] = themes[0]

        log(logger, f"[테마 자동 보정]\n{ticker}:\n{before} → {', '.join(themes)}")
        updated += 1
    return updated


def _verify_theme_patch_save(file_name: str, expected_items: list[dict[str, Any]], logger: Logger = None) -> None:
    verified = _load_local_json_file(file_name, [], required=True, logger=logger)
    if verified == expected_items:
        log(logger, f"{file_name} 자동 보정 저장 후 재로드 검증 성공: {len(expected_items)}개")
        return
    log(logger, f"{file_name} 자동 보정 저장 후 재로드 검증 실패: 저장 데이터가 재로드 데이터와 다릅니다.")


def patch_watchlist_themes(
    logger: Logger = None,
    *,
    ticker_theme_index: dict[str, list[str]] | None = None,
) -> int:
    index = ticker_theme_index or _theme_universe_ticker_index(logger=logger)
    if not index:
        return 0

    items = load_watchlist(logger=logger)
    updated = _patch_item_themes(items, index, logger=logger)
    if updated:
        save_watchlist(items, logger=logger)
        _verify_theme_patch_save(WATCHLIST_FILE, items, logger=logger)
    return updated


def patch_holdings_themes(
    logger: Logger = None,
    *,
    ticker_theme_index: dict[str, list[str]] | None = None,
) -> int:
    index = ticker_theme_index or _theme_universe_ticker_index(logger=logger)
    if not index:
        return 0

    items = load_holdings(logger=logger)
    updated = _patch_item_themes(items, index, logger=logger)
    if updated:
        save_holdings(items, logger=logger)
        _verify_theme_patch_save(HOLDINGS_FILE, items, logger=logger)
    return updated


def auto_patch_themes_from_universe(logger: Logger = None) -> dict[str, int]:
    index = _theme_universe_ticker_index(logger=logger)
    if not index:
        return {"watchlist": 0, "holdings": 0}
    return {
        "watchlist": patch_watchlist_themes(logger=logger, ticker_theme_index=index),
        "holdings": patch_holdings_themes(logger=logger, ticker_theme_index=index),
    }


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


def save_alerts(items: list[dict[str, Any]], logger: Logger = None) -> None:
    save_json_file(ALERTS_FILE, items, logger=logger)


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
    before_count = len(items)
    log(logger, f"기존 holdings: {before_count}개")
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

        log(logger, f"추가 후 holdings: {len(items)}개")
        save_holdings(items, logger=logger, previous_count=before_count, min_expected_count=before_count)
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
    log(logger, f"추가 후 holdings: {len(items)}개")
    save_holdings(items, logger=logger, previous_count=before_count, min_expected_count=before_count + 1)
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
