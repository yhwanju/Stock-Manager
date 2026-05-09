from __future__ import annotations

import analyzer
import storage


def help_text() -> str:
    return """━━━━━━━━━━
**🤖 주식관리봇 기능**
━━━━━━━━━━

/종목분석 종목명
→ 입력한 종목을 상세 분석합니다.

/강한테마종목
→ 오늘 강한 테마 기준 추천종목 3개 이름만 보여줍니다.

/관심추가 종목명
→ 티커와 테마를 자동으로 찾아 관심종목을 추가합니다. 예: /관심추가 엔비디아

/관심추가직접 종목명 티커 테마
→ 직접 입력해 관심종목을 추가합니다. 예: /관심추가직접 엔켐 348370.KQ 2차전지,ESS

/관심삭제 종목명
→ 관심종목을 삭제합니다. 예: /관심삭제 엔켐

/관심목록
→ 현재 관심종목 목록을 보여줍니다.

/관심매수 종목명 수량 평단
→ 관심종목을 보유종목으로 이동합니다. 예: /관심매수 HK이노엔 50 49500

/보유추가 종목명 수량 평단 [티커]
→ 보유종목을 추가하고 관심종목에서는 자동 제외합니다. 예: /보유추가 HK이노엔 50 49500

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


def _ticker_lookup_failed(name: str) -> str:
    return (
        f"종목명: **{name}**\n"
        "상태: **자동 매핑 실패**\n\n"
        "안내:\n"
        "ticker_map.json에 해당 종목이 없습니다.\n"
        "아래 형식으로 직접 추가하거나 ticker_map.json에 등록해주세요.\n\n"
        "/관심추가직접 종목명 티커 테마"
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
    ticker_map = storage.load_ticker_map()
    ticker, mapped_name = storage.resolve_ticker(name, ticker_map)
    if not ticker:
        return _ticker_lookup_failed(name)

    display_name = (
        mapped_name
        if mapped_name and (storage.normalize(name) == storage.normalize(ticker) or name.strip().isdigit())
        else name.strip()
    )
    theme_payload, _ = storage.find_theme_mapping(name, ticker, ticker_map=ticker_map)
    if not theme_payload or not theme_payload.get("themes"):
        return _theme_lookup_failed(display_name, ticker)

    holding = storage.find_item(storage.load_holdings(), display_name) or storage.find_item(storage.load_holdings(), ticker)
    if holding:
        return _already_held_message(holding)

    watchlist = storage.load_watchlist()
    existing = storage.find_item(watchlist, display_name) or storage.find_item(watchlist, ticker)
    if existing:
        return _format_watchlist_item("이미 관심종목에 있습니다.", existing)

    themes, subthemes, non_priority = _theme_fields_from_payload(theme_payload)
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


def _holding_lookup_failed(name: str) -> str:
    return (
        f"종목명: **{name}**\n"
        "상태: **티커 자동 매핑 실패**\n\n"
        "안내:\n"
        "ticker_map.json에 해당 종목이 없습니다.\n"
        "티커를 직접 입력하거나 ticker_map.json에 등록해주세요."
    )


def _holding_theme_fields(source: dict | None, query: str, ticker: str) -> tuple[list[str], list[str], list[str]]:
    if source:
        return analyzer.normalize_stock_theme_fields(source)

    ticker_map = storage.load_ticker_map()
    theme_payload, _ = storage.find_theme_mapping(query, ticker, ticker_map=ticker_map)
    if theme_payload:
        return _theme_fields_from_payload(theme_payload)
    return [], [], []


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
        f"평단: **{analyzer.format_krw(float(average_price))}**"
    )


def add_holding(name: str, quantity: int, average_price: float, ticker: str | None = None) -> str:
    clean_ticker = (ticker or "").strip()
    watchlist = storage.load_watchlist()
    watchlist_item = storage.find_item(watchlist, name)

    if not clean_ticker and watchlist_item:
        clean_ticker = str(watchlist_item.get("ticker", ""))

    mapped_name = None
    if not clean_ticker:
        clean_ticker, mapped_name = storage.resolve_ticker(name)
        if not clean_ticker:
            return _holding_lookup_failed(name)

    display_name = (
        mapped_name
        if mapped_name and (storage.normalize(name) == storage.normalize(clean_ticker) or name.strip().isdigit())
        else name.strip()
    )
    if watchlist_item:
        display_name = str(watchlist_item.get("name", display_name))

    themes, subthemes, non_priority = _holding_theme_fields(watchlist_item, name, clean_ticker)
    status, item = storage.upsert_holding(
        display_name,
        clean_ticker,
        quantity,
        average_price,
        themes,
        subthemes,
        non_priority,
    )
    removed = storage.delete_watchlist(clean_ticker) or storage.delete_watchlist(display_name)
    prefix = "보유종목 업데이트 완료" if status == "updated" else "보유종목 추가 완료"
    return _format_holding_result(prefix, item, bool(removed))


def buy_watchlist(name: str, quantity: int, average_price: float) -> str:
    watchlist = storage.load_watchlist()
    item = storage.find_item(watchlist, name)
    if not item:
        return (
            f"종목명: **{name}**\n"
            "상태: **관심종목 없음**\n\n"
            "안내:\n"
            "먼저 /관심추가로 관심종목에 등록하거나 /보유추가로 직접 추가해주세요."
        )

    themes, subthemes, non_priority = analyzer.normalize_stock_theme_fields(item)
    status, holding = storage.upsert_holding(
        str(item.get("name", name)),
        str(item.get("ticker", "")),
        quantity,
        average_price,
        themes,
        subthemes,
        non_priority,
    )
    removed = storage.delete_watchlist(str(item.get("ticker", name))) or storage.delete_watchlist(name)
    prefix = "관심매수 업데이트 완료" if status == "updated" else "관심매수 완료"
    return _format_holding_result(prefix, holding, bool(removed))


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
    storage.prune_watchlist_holdings_overlap()
    return analyzer.holdings_text()


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
