from __future__ import annotations

from datetime import datetime

import analyzer
import storage
from config import KST


def command_log(message: str) -> None:
    print(f"[stock-question-bot] {message}", flush=True)


def help_text() -> str:
    return """━━━━━━━━━━
**🤖 주식관리봇 기능**
━━━━━━━━━━

/종목분석 종목명
→ 입력한 종목을 상세 분석합니다.

/강한테마종목
→ 오늘 강한 테마 기준 추천종목 3개 이름만 보여줍니다.

/관심추가 종목명
→ 티커와 테마를 자동검색해 관심종목을 추가합니다. 예: /관심추가 풍산

/관심추가직접 종목명 티커 테마
→ 자동검색 실패 시 직접 입력합니다. 예: /관심추가직접 엔켐 348370.KQ 2차전지,ESS

/관심삭제 종목명
→ 관심종목을 삭제합니다. 예: /관심삭제 엔켐

/관심목록
→ 현재 관심종목 목록을 보여줍니다.

/종목매핑확인 종목명
→ 자동검색 결과를 확인합니다. 예: /종목매핑확인 풍산

/관심테마수정 종목명 테마
→ 관심/보유종목의 테마를 수정합니다. 예: /관심테마수정 풍산 원자재,방산

/관심매수 종목명 수량 매수가
→ 관심종목을 보유종목으로 이동하거나 자동 매핑으로 추가합니다. 예: /관심매수 HK이노엔 50 49500

/보유추가 종목명 수량 매수가
→ 신규매수 또는 추가매수를 반영합니다. 예: /보유추가 풍산 27 97888

/분할매도 종목명 수량 매도가
→ 보유 수량을 줄이고 실현손익을 기록합니다. 예: /분할매도 풍산 10 105000

/전량매도 종목명 매도가
→ 전체 수량을 매도 처리하고 보유목록에서 제거합니다. 예: /전량매도 풍산 105000

/보유수정 종목명 수량 평단
→ 오류 정정용으로 수량과 평단을 강제 수정합니다. 예: /보유수정 풍산 27 97888

/매매이력
/매매이력 종목명
→ 최근 매매이력 10건을 보여줍니다.

/성과추적
→ 정기 리포트 추천종목의 최근 성과를 보여줍니다.

/알고리즘성과
→ 추천 알고리즘의 전체 성과를 요약합니다.

평단 기준
→ 한국주식은 KRW, 미국주식은 USD 기준입니다. 원화/달러 자동 환산은 하지 않습니다.

/보유삭제 종목명
→ 보유종목을 삭제합니다.

/보유목록
→ 현재 보유종목 목록을 보여줍니다.

/포트폴리오점검
→ 보유종목 비중, 테마 편중, 리스크를 점검합니다.

/시장상태
→ 현재 시장 상태와 현금 비중 전략을 보여줍니다.

/오늘전략
→ 오늘 신규매수/관망/현금비중 전략을 보여줍니다.

/강한테마
→ 뉴스봇 기반 오늘 강한 테마를 보여줍니다.

/물림 종목명 평단
→ 손절가, 버틸 구간, 시간손절 기준을 분석합니다.

/테마점검 테마명
→ 해당 테마의 지속성, 과열도, 리스크를 점검합니다.

/알림설정 종목명 조건 가격
→ 목표가/손절가 알림 조건을 저장합니다. 예: /알림설정 HK이노엔 목표 56000"""


def stock_analysis(query: str) -> str:
    return analyzer.stock_detail_report(query)


def strong_theme_stocks() -> str:
    return analyzer.strong_theme_stock_names()


def _format_watchlist_item(prefix: str, item: dict, warning: str = "") -> str:
    theme_label = ", ".join(item.get("themes", [])) or "-"
    subtheme_label = ", ".join(item.get("subthemes", [])) or "-"
    return (
        f"{prefix}\n"
        f"종목명: **{item['name']}**\n"
        f"티커: **{item['ticker']}**\n"
        f"테마: **{theme_label}**\n"
        f"세부태그: **{subtheme_label}**"
        f"{warning}"
    )


def _theme_fields_from_payload(payload: dict) -> tuple[list[str], list[str], list[str]]:
    theme_config = storage.load_theme_config()
    themes, subthemes, non_priority = analyzer.resolve_theme_inputs(payload.get("themes", []), theme_config)
    for subtheme in analyzer.split_theme_values(payload.get("subthemes", [])):
        if subtheme not in subthemes:
            subthemes.append(subtheme)
    return themes, subthemes, non_priority


def _theme_fields_for_query(query: str, ticker: str, source: dict | None = None) -> tuple[list[str], list[str], list[str]]:
    if source:
        return analyzer.normalize_stock_theme_fields(source)
    theme_payload, _ = storage.find_theme_mapping(query, ticker)
    if theme_payload:
        return _theme_fields_from_payload(theme_payload)
    return ["미분류"], [], []


def _ticker_lookup_failed(name: str) -> str:
    return (
        f"종목명: **{name}**\n"
        "상태: **자동검색 실패**\n\n"
        "안내:\n"
        "1. 한국 종목이면 정확한 종목명을 입력해주세요.\n"
        "2. 미국 종목이면 티커로 입력해주세요. 예: NVDA, CRCL\n"
        "3. 그래도 안 되면 /관심추가직접을 사용해주세요."
    )


def _theme_lookup_failed(name: str, ticker: str) -> str:
    return (
        f"종목명: **{name}**\n"
        f"티커: **{ticker}**\n"
        "상태: **테마 자동 매핑 실패**\n\n"
        "안내:\n"
        "theme_map.json에 해당 종목이 없습니다.\n"
        "아래 형식으로 직접 추가하거나 theme_map.json에 등록해주세요.\n\n"
        "/관심추가직접 종목명 티커 테마"
    )


def _already_held_message(item: dict) -> str:
    return (
        f"종목명: **{item.get('name', '-')}**\n"
        "상태: **이미 보유종목**\n"
        "관심종목 처리: **추가 안 함**"
    )


def add_watchlist(name: str) -> str:
    resolution = analyzer.resolve_ticker(name)
    if not resolution:
        return _ticker_lookup_failed(name)

    display_name = resolution.name
    ticker = resolution.ticker
    holding = storage.find_item(storage.load_holdings(), display_name) or storage.find_item(storage.load_holdings(), ticker)
    if holding:
        return _already_held_message(holding)

    watchlist = storage.load_watchlist()
    existing = storage.find_item(watchlist, display_name) or storage.find_item(watchlist, ticker)
    if existing:
        return _format_watchlist_item("이미 관심종목에 있습니다.", existing)

    themes, subthemes, non_priority = _theme_fields_for_query(name, ticker)
    status, item = storage.upsert_watchlist(display_name, ticker, themes, subthemes, non_priority)
    warning = ""
    if non_priority:
        warning = f"\n경고: **{', '.join(non_priority)}**은(는) 비우선 테마로 저장했습니다."
    _ = status
    return _format_watchlist_item("관심종목을 추가했습니다.", item, warning)


def add_watchlist_manual(name: str, ticker: str, themes_text: str) -> str:
    holding = storage.find_item(storage.load_holdings(), name) or storage.find_item(storage.load_holdings(), ticker)
    if holding:
        return _already_held_message(holding)

    theme_config = storage.load_theme_config()
    themes, subthemes, non_priority = analyzer.resolve_theme_inputs(themes_text, theme_config)
    status, item = storage.upsert_watchlist(name, ticker, themes, subthemes, non_priority)
    warning = ""
    if non_priority:
        warning = f"\n경고: **{', '.join(non_priority)}**은(는) 비우선 테마로 저장했습니다."
    if status == "updated":
        return _format_watchlist_item("관심종목 중복으로 업데이트했습니다.", item, warning)
    return _format_watchlist_item("관심종목을 추가했습니다.", item, warning)


def delete_watchlist(query: str) -> str:
    item = storage.delete_watchlist(query)
    if not item:
        return f"관심종목에서 **{query}**을(를) 찾지 못했습니다."
    return f"관심종목을 삭제했습니다.\n종목명: **{item['name']}**"


def list_watchlist() -> str:
    storage.prune_watchlist_holdings_overlap()
    return analyzer.watchlist_text()


def mapping_check(name: str) -> str:
    resolution = analyzer.resolve_ticker(name)
    if not resolution:
        return _ticker_lookup_failed(name)

    themes, _, _ = _theme_fields_for_query(name, resolution.ticker)
    theme_label = ", ".join(themes) or "미분류"
    return (
        f"종목명: **{resolution.name}**\n"
        f"티커: **{resolution.ticker}**\n"
        f"검색방식: **{resolution.search_method}**\n"
        f"테마: **{theme_label}**"
    )


def update_item_theme(name: str, themes_text: str) -> str:
    themes, subthemes, non_priority = analyzer.resolve_theme_inputs(themes_text, storage.load_theme_config())
    if not themes:
        return "테마를 입력해주세요. 예: /관심테마수정 풍산 원자재,방산"

    watchlist = storage.load_watchlist()
    item = storage.find_item(watchlist, name)
    target = "관심종목"
    if item:
        item["themes"] = themes
        item["subthemes"] = subthemes
        if non_priority:
            item["non_priority_themes"] = non_priority
        else:
            item.pop("non_priority_themes", None)
        storage.save_watchlist(watchlist)
    else:
        holdings = storage.load_holdings()
        item = storage.find_item(holdings, name)
        target = "보유종목"
        if not item:
            return f"종목명: **{name}**\n상태: **종목 없음**"
        item["themes"] = themes
        item["subthemes"] = subthemes
        if non_priority:
            item["non_priority_themes"] = non_priority
        else:
            item.pop("non_priority_themes", None)
        storage.save_holdings(holdings)

    theme_label = ", ".join(themes) or "-"
    subtheme_label = ", ".join(subthemes) or "-"
    return (
        f"종목명: **{item.get('name', name)}**\n"
        f"대상: **{target}**\n"
        "상태: **테마 수정 완료**\n"
        f"테마: **{theme_label}**\n"
        f"세부태그: **{subtheme_label}**"
    )


def _holding_lookup_failed(name: str) -> str:
    return (
        f"종목명: **{name}**\n"
        "상태: **자동검색 실패**\n\n"
        "안내:\n"
        "1. 한국 종목이면 정확한 종목명을 입력해주세요.\n"
        "2. 미국 종목이면 티커로 입력해주세요. 예: NVDA, CRCL\n"
        "3. 그래도 안 되면 /관심추가직접을 사용해주세요."
    )


def _holding_theme_fields(source: dict | None, query: str, ticker: str) -> tuple[list[str], list[str], list[str]]:
    return _theme_fields_for_query(query, ticker, source)


def _format_holding_result(prefix: str, item: dict, watchlist_removed: bool) -> str:
    quantity_text = f"{int(item['quantity']):,}주"
    average_price = item.get("avg_price", item.get("average_price", 0))
    watchlist_status = "자동 제외 완료" if watchlist_removed else "제외 대상 없음"
    return (
        f"종목명: **{item['name']}**\n"
        f"상태: **{prefix}**\n"
        f"관심종목 처리: **{watchlist_status}**\n"
        f"티커: **{item['ticker']}**\n"
        f"보유수량: **{quantity_text}**\n"
        f"평단: **{analyzer.format_price_for_ticker(float(average_price), str(item['ticker']))}**"
    )


def _holding_save_failed_message(name: str, status: str, detail: str) -> str:
    return (
        f"종목명: **{name}**\n"
        f"상태: **{status}**\n\n"
        "안내:\n"
        f"{detail}"
    )


def _format_signed_money(value: float | int | None, ticker: str) -> str:
    if value is None:
        return "-"
    numeric = float(value)
    sign = "+" if numeric > 0 else "-" if numeric < 0 else ""
    absolute = abs(numeric)
    if analyzer.is_korean_stock_ticker(ticker):
        return f"{sign}{absolute:,.0f}원"
    return f"{sign}${absolute:,.2f}"


def _format_quantity_price(quantity: int, price: float, ticker: str) -> str:
    return f"{int(quantity):,}주 / {analyzer.format_price_for_ticker(float(price), ticker)}"


def _trade_now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _trade_entry(
    trade_type: str,
    item: dict,
    quantity: int,
    price: float,
    avg_price_before: float | None,
    avg_price_after: float | None,
    realized_profit: float = 0.0,
    realized_return_pct: float = 0.0,
    remaining_quantity: int = 0,
    memo: str = "",
) -> dict:
    return {
        "date": _trade_now(),
        "type": trade_type,
        "name": item.get("name", "-"),
        "ticker": item.get("ticker", "-"),
        "quantity": int(quantity),
        "price": float(price),
        "avg_price_before": float(avg_price_before) if avg_price_before is not None else None,
        "avg_price_after": float(avg_price_after) if avg_price_after is not None else None,
        "realized_profit": float(realized_profit),
        "realized_return_pct": float(realized_return_pct),
        "remaining_quantity": int(remaining_quantity),
        "memo": memo,
    }


def _record_trade_with_verification(entry: dict) -> bool:
    storage.record_trade(entry, logger=command_log)
    return storage.verify_trade_saved(entry, logger=command_log)


def _find_holding_for_query(query: str) -> tuple[list[dict], dict | None]:
    holdings = storage.load_holdings(logger=command_log)
    item = storage.find_item(holdings, query)
    if item:
        return holdings, item

    resolution = analyzer.resolve_ticker(query)
    if resolution:
        item = storage.find_item(holdings, resolution.ticker) or storage.find_item(holdings, resolution.name)
    return holdings, item


def _holding_not_found_message(query: str) -> str:
    return (
        f"종목명: **{query}**\n"
        "상태: **보유종목 없음**\n\n"
        "안내:\n"
        "/보유목록에서 현재 보유 중인 종목명을 확인해주세요."
    )


def _mapped_holding_payload(name: str) -> tuple[str, str, list[str], list[str], list[str], dict | None] | None:
    resolution = analyzer.resolve_ticker(name)
    if not resolution:
        return None

    watchlist = storage.load_watchlist()
    watchlist_item = storage.find_item(watchlist, name) or storage.find_item(watchlist, resolution.ticker)
    display_name = resolution.name
    if watchlist_item:
        display_name = str(watchlist_item.get("name", display_name))

    themes, subthemes, non_priority = _holding_theme_fields(watchlist_item, name, resolution.ticker)
    return display_name, resolution.ticker, themes, subthemes, non_priority, watchlist_item


def add_holding(name: str, quantity: int, average_price: float) -> str:
    resolved = _mapped_holding_payload(name)
    if not resolved:
        return _holding_lookup_failed(name)

    display_name, ticker, themes, subthemes, non_priority, _ = resolved
    command_log(f"/보유추가 저장 시작: {display_name} / {ticker} / 저장소: {storage.storage_location_text(storage.HOLDINGS_FILE)}")
    try:
        status, item, before = storage.buy_holding(
            display_name,
            ticker,
            quantity,
            average_price,
            themes,
            subthemes,
            non_priority,
            logger=command_log,
        )
        verified = storage.verify_holding_saved(display_name, ticker, logger=command_log)
    except Exception as exc:
        command_log(f"/보유추가 저장 실패: {display_name} / {ticker} / {exc}")
        return _holding_save_failed_message(display_name, "저장 실패", f"보유 데이터 저장 중 오류가 발생했습니다.\n오류: **{exc}**")

    if not verified:
        return _holding_save_failed_message(
            display_name,
            "저장 검증 실패",
            "보유 데이터에 저장 직후 다시 조회했지만 종목을 찾지 못했습니다.",
        )

    old_quantity = int(before.get("quantity", 0)) if before else 0
    old_average_price = float(before.get("avg_price", before.get("average_price", 0))) if before else None
    current_quantity = int(verified["quantity"])
    current_average_price = float(verified.get("avg_price", verified.get("average_price", 0)))
    trade = _trade_entry(
        "BUY",
        verified,
        int(quantity),
        float(average_price),
        old_average_price,
        current_average_price,
        remaining_quantity=current_quantity,
        memo="추가매수" if before else "신규매수",
    )
    if not _record_trade_with_verification(trade):
        return _holding_save_failed_message(display_name, "매매이력 저장 검증 실패", "매매이력에 BUY 이력을 저장했지만 다시 조회하지 못했습니다.")

    removed = storage.delete_watchlist(ticker) or storage.delete_watchlist(display_name) or storage.delete_watchlist(name)
    watchlist_status = "자동 제외 완료" if removed else "제외 대상 없음"

    if status == "additional_buy":
        return (
            f"종목명: **{verified['name']}**\n"
            "상태: **추가매수 반영 완료**\n"
            f"관심종목 처리: **{watchlist_status}**\n\n"
            "기존:\n"
            f"{_format_quantity_price(old_quantity, old_average_price or 0, ticker)}\n\n"
            "추가:\n"
            f"{_format_quantity_price(int(quantity), float(average_price), ticker)}\n\n"
            "현재:\n"
            f"{_format_quantity_price(current_quantity, current_average_price, ticker)}"
        )

    return _format_holding_result("신규 보유종목 추가 완료", verified or item, bool(removed))


def buy_watchlist(name: str, quantity: int, average_price: float) -> str:
    watchlist = storage.load_watchlist()
    item = storage.find_item(watchlist, name)
    if not item:
        resolution = analyzer.resolve_ticker(name)
        if resolution:
            item = storage.find_item(watchlist, resolution.ticker)

    if item:
        themes, subthemes, non_priority = analyzer.normalize_stock_theme_fields(item)
        display_name = str(item.get("name", name))
        ticker = str(item.get("ticker", ""))
    else:
        resolved = _mapped_holding_payload(name)
        if not resolved:
            return _holding_lookup_failed(name)
        display_name, ticker, themes, subthemes, non_priority, _ = resolved

    command_log(f"/관심매수 저장 시작: {display_name} / {ticker} / 저장소: {storage.storage_location_text(storage.HOLDINGS_FILE)}")
    try:
        status, holding, before = storage.buy_holding(
            display_name,
            ticker,
            quantity,
            average_price,
            themes,
            subthemes,
            non_priority,
            logger=command_log,
        )
        verified = storage.verify_holding_saved(display_name, ticker, logger=command_log)
    except Exception as exc:
        command_log(f"/관심매수 저장 실패: {display_name} / {ticker} / {exc}")
        return _holding_save_failed_message(display_name, "저장 실패", f"보유 데이터 저장 중 오류가 발생했습니다.\n오류: **{exc}**")

    if not verified:
        return _holding_save_failed_message(
            display_name,
            "저장 검증 실패",
            "보유 데이터에 저장 직후 다시 조회했지만 종목을 찾지 못했습니다.",
        )

    current_average_price = float(verified.get("avg_price", verified.get("average_price", 0)))
    trade = _trade_entry(
        "BUY",
        verified,
        int(quantity),
        float(average_price),
        float(before.get("avg_price", before.get("average_price", 0))) if before else None,
        current_average_price,
        remaining_quantity=int(verified["quantity"]),
        memo="관심매수 추가매수" if status == "additional_buy" else "관심매수 신규매수",
    )
    if not _record_trade_with_verification(trade):
        return _holding_save_failed_message(display_name, "매매이력 저장 검증 실패", "매매이력에 BUY 이력을 저장했지만 다시 조회하지 못했습니다.")

    removed = storage.delete_watchlist(ticker) or storage.delete_watchlist(display_name) or storage.delete_watchlist(name)
    prefix = "관심매수 추가매수 반영 완료" if status == "additional_buy" else "관심매수 완료"
    return _format_holding_result(prefix, verified or holding, bool(removed))


def partial_sell(name: str, quantity: int, sell_price: float) -> str:
    holdings, item = _find_holding_for_query(name)
    if not item:
        return _holding_not_found_message(name)

    sell_quantity = int(quantity)
    held_quantity = int(item.get("quantity", 0) or 0)
    ticker = str(item.get("ticker", ""))
    avg_price = float(item.get("avg_price", item.get("average_price", 0)) or 0)
    sell_price_value = float(sell_price)
    if sell_quantity <= 0:
        return _holding_save_failed_message(str(item.get("name", name)), "매도 실패", "매도 수량은 1 이상이어야 합니다.")
    if sell_price_value <= 0:
        return _holding_save_failed_message(str(item.get("name", name)), "매도 실패", "매도가는 0보다 커야 합니다.")
    if sell_quantity > held_quantity:
        return (
            f"종목명: **{item.get('name', name)}**\n"
            "상태: **매도 수량 초과**\n\n"
            f"보유수량: **{held_quantity:,}주**\n"
            f"요청수량: **{sell_quantity:,}주**"
        )

    before = item.copy()
    remaining_quantity = held_quantity - sell_quantity
    realized_profit = (sell_price_value - avg_price) * sell_quantity
    realized_return_pct = ((sell_price_value - avg_price) / avg_price) * 100 if avg_price else 0.0

    if remaining_quantity > 0:
        item["quantity"] = remaining_quantity
        storage.save_holdings(holdings, logger=command_log)
        holding_verified = storage.verify_holding_saved(str(item.get("name", name)), ticker, logger=command_log)
    else:
        storage.save_holdings([holding for holding in holdings if holding is not item], logger=command_log)
        holding_verified = storage.verify_holding_removed(str(item.get("name", name)), ticker, logger=command_log)

    if not holding_verified:
        return _holding_save_failed_message(str(before.get("name", name)), "저장 검증 실패", "매도 후 보유 데이터 검증에 실패했습니다.")

    trade_type = "PARTIAL_SELL" if remaining_quantity > 0 else "FULL_SELL"
    trade = _trade_entry(
        trade_type,
        before,
        sell_quantity,
        sell_price_value,
        avg_price,
        avg_price if remaining_quantity > 0 else None,
        realized_profit=realized_profit,
        realized_return_pct=realized_return_pct,
        remaining_quantity=remaining_quantity,
        memo="분할매도" if remaining_quantity > 0 else "분할매도 후 잔여수량 0",
    )
    if not _record_trade_with_verification(trade):
        return _holding_save_failed_message(str(before.get("name", name)), "매매이력 저장 검증 실패", "매매이력에 매도 이력을 저장했지만 다시 조회하지 못했습니다.")

    status = "분할매도 반영 완료" if remaining_quantity > 0 else "전량매도 완료"
    remaining_text = (
        f"{remaining_quantity:,}주 / 평단 {analyzer.format_price_for_ticker(avg_price, ticker)}"
        if remaining_quantity > 0
        else "보유목록에서 제거 완료"
    )
    return (
        f"종목명: **{before.get('name', name)}**\n"
        f"상태: **{status}**\n\n"
        "매도:\n"
        f"{_format_quantity_price(sell_quantity, sell_price_value, ticker)}\n\n"
        "실현손익:\n"
        f"{_format_signed_money(realized_profit, ticker)} / {analyzer.format_pct(realized_return_pct)}\n\n"
        "잔여:\n"
        f"{remaining_text}"
    )


def full_sell(name: str, sell_price: float) -> str:
    holdings, item = _find_holding_for_query(name)
    if not item:
        return _holding_not_found_message(name)

    quantity = int(item.get("quantity", 0) or 0)
    if quantity <= 0:
        return _holding_save_failed_message(str(item.get("name", name)), "전량매도 실패", "보유 수량이 없습니다.")

    ticker = str(item.get("ticker", ""))
    avg_price = float(item.get("avg_price", item.get("average_price", 0)) or 0)
    sell_price_value = float(sell_price)
    if sell_price_value <= 0:
        return _holding_save_failed_message(str(item.get("name", name)), "전량매도 실패", "매도가는 0보다 커야 합니다.")

    before = item.copy()
    realized_profit = (sell_price_value - avg_price) * quantity
    realized_return_pct = ((sell_price_value - avg_price) / avg_price) * 100 if avg_price else 0.0
    storage.save_holdings([holding for holding in holdings if holding is not item], logger=command_log)
    if not storage.verify_holding_removed(str(before.get("name", name)), ticker, logger=command_log):
        return _holding_save_failed_message(str(before.get("name", name)), "저장 검증 실패", "전량매도 후 보유 데이터 제거 검증에 실패했습니다.")

    trade = _trade_entry(
        "FULL_SELL",
        before,
        quantity,
        sell_price_value,
        avg_price,
        None,
        realized_profit=realized_profit,
        realized_return_pct=realized_return_pct,
        remaining_quantity=0,
        memo="전량매도",
    )
    if not _record_trade_with_verification(trade):
        return _holding_save_failed_message(str(before.get("name", name)), "매매이력 저장 검증 실패", "매매이력에 전량매도 이력을 저장했지만 다시 조회하지 못했습니다.")

    return (
        f"종목명: **{before.get('name', name)}**\n"
        "상태: **전량매도 완료**\n\n"
        "매도:\n"
        f"{_format_quantity_price(quantity, sell_price_value, ticker)}\n\n"
        "실현손익:\n"
        f"{_format_signed_money(realized_profit, ticker)} / {analyzer.format_pct(realized_return_pct)}\n\n"
        "보유상태:\n"
        "보유목록에서 제거 완료"
    )


def edit_holding(name: str, quantity: int, average_price: float) -> str:
    holdings, existing = _find_holding_for_query(name)
    if existing:
        display_name = str(existing.get("name", name))
        ticker = str(existing.get("ticker", ""))
        themes, subthemes, non_priority = analyzer.normalize_stock_theme_fields(existing)
        before = existing.copy()
    else:
        resolved = _mapped_holding_payload(name)
        if not resolved:
            return _holding_lookup_failed(name)
        display_name, ticker, themes, subthemes, non_priority, _ = resolved
        before = None

    try:
        status, item, _ = storage.replace_holding(
            display_name,
            ticker,
            quantity,
            average_price,
            themes,
            subthemes,
            non_priority,
            logger=command_log,
        )
        verified = storage.verify_holding_saved(display_name, ticker, logger=command_log)
    except Exception as exc:
        return _holding_save_failed_message(display_name, "보유수정 실패", f"보유 데이터 수정 중 오류가 발생했습니다.\n오류: **{exc}**")

    if not verified:
        return _holding_save_failed_message(display_name, "저장 검증 실패", "보유수정 후 보유 데이터 검증에 실패했습니다.")

    history_count = len(storage.load_trade_history(logger=command_log))
    command_log(f"/보유수정 매매이력 읽음: {history_count}건 / 수동수정은 이력 미기록")

    before_text = (
        f"{int(before.get('quantity', 0)):,}주 / {analyzer.format_price_for_ticker(float(before.get('avg_price', before.get('average_price', 0))), ticker)}"
        if before
        else "기존 보유 없음"
    )
    current_text = _format_quantity_price(int(verified["quantity"]), float(verified.get("avg_price", verified.get("average_price", 0))), ticker)
    _ = status
    _ = item
    _ = holdings
    return (
        f"종목명: **{verified['name']}**\n"
        "상태: **보유수정 완료**\n"
        "매매이력 기록: **안 함**\n\n"
        "기존:\n"
        f"{before_text}\n\n"
        "현재:\n"
        f"{current_text}"
    )


def trade_history(query: str | None = None) -> str:
    history = storage.load_trade_history(logger=command_log)
    filtered = history
    title = "전체"
    if query:
        resolution = analyzer.resolve_ticker(query)
        query_keys = {storage.normalize(query)}
        if resolution:
            query_keys.update({storage.normalize(resolution.name), storage.normalize(resolution.ticker)})
            title = resolution.name
        else:
            title = query
        filtered = [
            item for item in history
            if storage.normalize(str(item.get("name", ""))) in query_keys
            or storage.normalize(str(item.get("ticker", ""))) in query_keys
        ]

    lines = analyzer.section("🧾 매매이력")
    lines.append(f"조회대상: **{title}**")
    lines.append("")
    if not filtered:
        lines.append("매매이력 없음")
        return "\n".join(lines).strip()

    for item in list(reversed(filtered))[:10]:
        ticker = str(item.get("ticker", ""))
        realized_profit = float(item.get("realized_profit", 0) or 0)
        realized_return_pct = float(item.get("realized_return_pct", 0) or 0)
        lines.append(f"종목명: **{item.get('name', '-')}**")
        lines.append(f"구분: **{item.get('type', '-')}**")
        lines.append(f"일시: **{item.get('date', '-')}**")
        lines.append(f"수량/가격: **{_format_quantity_price(int(item.get('quantity', 0) or 0), float(item.get('price', 0) or 0), ticker)}**")
        if item.get("type") in {"PARTIAL_SELL", "FULL_SELL"}:
            lines.append(f"실현손익: **{_format_signed_money(realized_profit, ticker)} / {analyzer.format_pct(realized_return_pct)}**")
        lines.append(f"잔여수량: **{int(item.get('remaining_quantity', 0) or 0):,}주**")
        memo = str(item.get("memo", "") or "-")
        lines.append(f"메모: **{memo}**")
        lines.append("")

    return "\n".join(lines).strip()


def _recommendation_return(item: dict[str, object]) -> tuple[float | None, float | None, str | None]:
    ticker = str(item.get("ticker", "") or "")
    entry_price = float(item.get("price", 0) or 0)
    if not ticker or entry_price <= 0:
        return None, None, "추천 당시 기준가 없음"

    analysis = analyzer.analyze_stock(
        {
            "name": str(item.get("name", ticker) or ticker),
            "ticker": ticker,
            "themes": item.get("themes", []) if isinstance(item.get("themes", []), list) else [],
        },
        [],
        str(item.get("market_state", "횡보장") or "횡보장"),
    )
    if analysis.error or not analysis.current_price:
        return entry_price, None, analysis.error or "현재가 조회 실패"

    return_pct = ((analysis.current_price / entry_price) - 1) * 100
    return entry_price, return_pct, None


def recommendation_performance() -> str:
    history = storage.load_recommendation_history(logger=command_log)
    lines = analyzer.section("📈 성과추적")
    if not history:
        lines.append("추천이력 없음")
        return "\n".join(lines).strip()

    lines.append("기준: **최근 추천 10건**")
    lines.append("")
    for item in list(reversed(history))[:10]:
        ticker = str(item.get("ticker", "") or "")
        entry_price, return_pct, error = _recommendation_return(item)
        lines.append(f"종목명: **{item.get('name', '-')}**")
        lines.append(f"추천일: **{item.get('date', '-')}**")
        lines.append(f"액션: **{item.get('action', '-')}**")
        if entry_price:
            lines.append(f"추천 기준가: **{analyzer.format_price_for_ticker(entry_price, ticker)}**")
        if return_pct is not None:
            lines.append(f"현재 성과: **{analyzer.format_pct(return_pct)}**")
        else:
            lines.append(f"현재 성과: **조회불가**")
            if error:
                lines.append(f"사유: **{error}**")
        lines.append("")

    return "\n".join(lines).strip()


def algorithm_performance() -> str:
    history = storage.load_recommendation_history(logger=command_log)
    lines = analyzer.section("📊 알고리즘성과")
    if not history:
        lines.append("추천이력 없음")
        return "\n".join(lines).strip()

    assessed: list[tuple[dict[str, object], float]] = []
    skipped = 0
    for item in list(reversed(history))[:30]:
        _, return_pct, _ = _recommendation_return(item)
        if return_pct is None:
            skipped += 1
            continue
        assessed.append((item, return_pct))

    if not assessed:
        lines.append(f"분석 가능 이력: **0건**")
        lines.append(f"조회 제외: **{skipped}건**")
        return "\n".join(lines).strip()

    returns = [value for _, value in assessed]
    wins = [value for value in returns if value > 0]
    avg_return = sum(returns) / len(returns)
    win_rate = len(wins) / len(returns) * 100
    best_item, best_return = max(assessed, key=lambda pair: pair[1])
    worst_item, worst_return = min(assessed, key=lambda pair: pair[1])

    lines.append(f"분석 기준: **최근 최대 30건**")
    lines.append(f"분석 가능 이력: **{len(assessed)}건**")
    lines.append(f"승률: **{win_rate:.1f}%**")
    lines.append(f"평균 성과: **{analyzer.format_pct(avg_return)}**")
    lines.append("")
    lines.append(f"최고 성과: **{best_item.get('name', '-')} / {analyzer.format_pct(best_return)}**")
    lines.append(f"최저 성과: **{worst_item.get('name', '-')} / {analyzer.format_pct(worst_return)}**")
    if skipped:
        lines.append("")
        lines.append(f"조회 제외: **{skipped}건**")

    return "\n".join(lines).strip()


def delete_holding(query: str) -> str:
    item = storage.delete_holding(query)
    if not item:
        return f"보유종목에서 **{query}**을(를) 찾지 못했습니다."
    return (
        "보유종목을 삭제했습니다.\n"
        f"종목명: **{item['name']}**\n"
        "관심종목 복귀: **자동 복귀 안 함**"
    )


def list_holdings() -> str:
    storage.prune_watchlist_holdings_overlap(logger=command_log)
    items = storage.load_holdings(logger=command_log)
    command_log(f"/보유목록 holdings 읽음: {len(items)}개 / 저장소: {storage.storage_location_text(storage.HOLDINGS_FILE)}")
    return analyzer.holdings_text(items=items, logger=command_log)


def portfolio_check() -> str:
    return analyzer.portfolio_check_report()


def market_status() -> str:
    return analyzer.market_status_report()


def today_strategy() -> str:
    return analyzer.today_strategy_report()


def strong_themes() -> str:
    return analyzer.strong_themes_report()


def stuck(query: str, average_price: float) -> str:
    return analyzer.stuck_report(query, average_price)


def theme_check(theme: str) -> str:
    return analyzer.theme_check_report(theme)


def set_alert(name: str, condition: str, price: float) -> str:
    normalized = condition.strip()
    if normalized not in {"목표", "손절"}:
        return "조건은 **목표** 또는 **손절**만 사용할 수 있습니다."
    alert = storage.add_alert(name, normalized, price)
    return (
        "알림 조건을 저장했습니다.\n"
        f"종목명: **{alert['name']}**\n"
        f"조건: **{alert['condition']}**\n"
        f"가격: **{analyzer.format_krw(float(alert['price']))}**"
    )
