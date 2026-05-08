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

/관심추가 종목명 티커
→ 관심종목을 추가합니다. 예: /관심추가 엔켐 348370.KQ

/관심삭제 종목명
→ 관심종목을 삭제합니다. 예: /관심삭제 엔켐

/관심목록
→ 현재 관심종목 목록을 보여줍니다.

/보유추가 종목명 티커 수량 평단
→ 보유종목을 추가합니다. 예: /보유추가 HK이노엔 195940.KQ 50 49500

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


def add_watchlist(name: str, ticker: str) -> str:
    status, item = storage.upsert_watchlist(name, ticker)
    if status == "updated":
        return f"관심종목 중복으로 업데이트했습니다.\n종목명: **{item['name']}**\n티커: **{item['ticker']}**"
    return f"관심종목을 추가했습니다.\n종목명: **{item['name']}**\n티커: **{item['ticker']}**"


def delete_watchlist(query: str) -> str:
    item = storage.delete_watchlist(query)
    if not item:
        return f"관심종목에서 **{query}**을(를) 찾지 못했습니다."
    return f"관심종목을 삭제했습니다.\n종목명: **{item['name']}**"


def list_watchlist() -> str:
    return analyzer.watchlist_text()


def add_holding(name: str, ticker: str, quantity: int, average_price: float) -> str:
    status, item = storage.upsert_holding(name, ticker, quantity, average_price)
    verb = "업데이트했습니다" if status == "updated" else "추가했습니다"
    quantity_text = f"{int(item['quantity']):,}주"
    return (
        f"보유종목을 {verb}.\n"
        f"종목명: **{item['name']}**\n"
        f"티커: **{item['ticker']}**\n"
        f"보유수량: **{quantity_text}**\n"
        f"평단: **{analyzer.format_krw(float(item['average_price']))}**"
    )


def delete_holding(query: str) -> str:
    item = storage.delete_holding(query)
    if not item:
        return f"보유종목에서 **{query}**을(를) 찾지 못했습니다."
    return f"보유종목을 삭제했습니다.\n종목명: **{item['name']}**"


def list_holdings() -> str:
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
