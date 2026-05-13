from __future__ import annotations

from datetime import datetime
from typing import Callable

import analyzer
import storage
from config import KST

Logger = Callable[[str], None] | None


def _line_after(block: str, label: str) -> str:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(label):
            if ":" in line and line.split(":", 1)[1].strip():
                return line.split(":", 1)[1].strip()
            if index + 1 < len(lines):
                return lines[index + 1].strip()
    return "-"


def _plain(value: str) -> str:
    return value.replace("**", "").strip()


def _price_only(value: str) -> str:
    text = _plain(value)
    for emoji in ("🟢", "🟡", "🔴"):
        text = text.replace(emoji, "")
    return text.strip() or "-"


def _target_summary(block: str) -> list[str]:
    targets = [
        ("🟢", "1차 목표가", _price_only(_line_after(block, "1차 목표가:"))),
        ("🟡", "2차 목표가", _price_only(_line_after(block, "2차 목표가:"))),
        ("🔴", "최종 목표가", _price_only(_line_after(block, "최종 목표가:"))),
    ]
    lines = ["목표가 요약:"]
    for emoji, label, price in targets:
        lines.append(f"{emoji} {label}: **{price}**")
    return lines


def _section_from_report(report: str, title: str) -> str:
    marker = f"**{title}**"
    start = report.find(marker)
    if start < 0:
        return ""
    next_start = report.find("━━━━━━━━━━", start + len(marker))
    if next_start < 0:
        return report[start:]
    # skip current section delimiter/title/delimiter and find the following delimiter
    next_start = report.find("━━━━━━━━━━", next_start + len("━━━━━━━━━━"))
    if next_start < 0:
        return report[start:]
    return report[start:next_start]


def _extract_basic_line(report: str, label: str) -> str:
    for line in report.splitlines():
        if line.strip().startswith(label):
            return line.strip()
    return ""


def _holding_keys() -> set[str]:
    keys: set[str] = set()
    for item in storage.load_holdings():
        name = str(item.get("name", "")).strip()
        ticker = str(item.get("ticker", "")).strip()
        if name:
            keys.add(analyzer.normalize_text(name))
        if ticker:
            keys.add(analyzer.normalize_text(ticker))
    return keys


def _candidate_keys(name: str) -> set[str]:
    normalized_name = analyzer.normalize_text(name)
    keys = {normalized_name} if normalized_name else set()
    for loader in (storage.load_watchlist, storage.load_holdings):
        try:
            items = loader()
        except Exception:
            items = []
        for item in items:
            item_name = analyzer.normalize_text(str(item.get("name", "")))
            item_ticker = analyzer.normalize_text(str(item.get("ticker", "")))
            if normalized_name and normalized_name in {item_name, item_ticker}:
                if item_name:
                    keys.add(item_name)
                if item_ticker:
                    keys.add(item_ticker)
    try:
        ticker_map = storage.load_ticker_map()
    except Exception:
        ticker_map = {}
    for map_name, ticker in ticker_map.items():
        if analyzer.normalize_text(str(map_name)) == normalized_name:
            keys.add(analyzer.normalize_text(str(ticker)))
    return keys


def _split_stock_blocks(section_text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in section_text.splitlines():
        if line.startswith("종목명:") and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        elif current or line.startswith("종목명:"):
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def _recommendation_blocks(original_report: str) -> list[str]:
    if "**🏆 추천 종목 TOP3**" not in original_report:
        return []
    start = original_report.find("**🏆 추천 종목 TOP3**")
    end = original_report.find("**👀 관심종목 점검**", start)
    text = original_report[start:end if end > 0 else len(original_report)]
    held = _holding_keys()
    result: list[str] = []
    for block in _split_stock_blocks(text):
        name = _plain(_line_after(block, "종목명:"))
        if _candidate_keys(name) & held:
            continue
        action = _plain(_line_after(block, "액션:"))
        entry = _plain(_line_after(block, "진입 가능 구간:"))
        stop = _plain(_line_after(block, "손절가:"))
        result.extend([
            f"종목명: **{name}**",
            f"액션: **{action}**",
            f"진입구간: **{entry}**",
            f"손절가: **{stop}**",
            *_target_summary(block),
            "",
        ])
    if not result:
        result.append("신규 추천 없음: **보유종목 중복 또는 조건 미충족**")
    return result


def _watchlist_summary(original_report: str, limit: int = 3) -> list[str]:
    if "**👀 관심종목 점검**" not in original_report:
        return []
    start = original_report.find("**👀 관심종목 점검**")
    text = original_report[start:]
    result: list[str] = []
    for block in _split_stock_blocks(text)[:limit]:
        name = _plain(_line_after(block, "종목명:"))
        state = _plain(_line_after(block, "상태:"))
        action = _plain(_line_after(block, "액션:"))
        result.append(f"{name}: **{state} / {action}**")
    return result


def _holding_summary(original_report: str) -> list[str]:
    result: list[str] = []
    for block in _split_stock_blocks(original_report):
        name = _plain(_line_after(block, "종목명:"))
        quantity = _plain(_line_after(block, "보유수량:"))
        average_price = _plain(_line_after(block, "평단:"))
        current_price = _plain(_line_after(block, "현재가:"))
        return_pct = _plain(_line_after(block, "수익률:"))
        action = _plain(_line_after(block, "액션:"))
        stop = _plain(_line_after(block, "손절가:"))
        if not name or name == "-":
            continue
        result.extend([
            f"종목명: **{name}**",
            f"보유수량: **{quantity}**",
            f"평단: **{average_price}**",
            f"현재가: **{current_price}**",
            f"수익률: **{return_pct}**",
            f"액션: **{action}**",
            f"손절가: **{stop}**",
            "",
        ])
    return result or ["보유종목 없음"]


def _slim_market_report(original_report: str) -> str:
    lines: list[str] = [
        "📊 **주식관리 리포트**",
        f"발송일: **{datetime.now(KST):%Y-%m-%d %H:%M} KST**",
        "",
        "━━━━━━━━━━",
        "**🌎 시장 상태**",
        "━━━━━━━━━━",
    ]
    for label in ("시장 상태:", "현금 비중 권고:"):
        value = _extract_basic_line(original_report, label)
        if value:
            lines.append(value)
    lines.extend(["", "━━━━━━━━━━", "**⚡ 오늘 액션 요약**", "━━━━━━━━━━"])
    for label in ("* 신규진입:", "* 보유종목:", "* 매매원칙:"):
        value = _extract_basic_line(original_report, label)
        if value:
            lines.append(value)
    lines.extend(["", "━━━━━━━━━━", "**🔥 오늘 강한 테마**", "━━━━━━━━━━"])
    theme_section = _section_from_report(original_report, "🔥 오늘 강한 테마")
    theme_lines = [line for line in theme_section.splitlines() if line.strip().startswith(("1.", "2.", "3."))]
    lines.extend(theme_lines[:3] or ["강한 테마 없음"])
    lines.extend(["", "━━━━━━━━━━", "**🏆 신규 추천 TOP3**", "━━━━━━━━━━"])
    lines.extend(_recommendation_blocks(original_report))
    watch = _watchlist_summary(original_report)
    if watch:
        lines.extend(["", "━━━━━━━━━━", "**👀 관심종목 요약**", "━━━━━━━━━━"])
        lines.extend(watch)
    return "\n".join(lines).strip()


def _slim_holdings_report(original_report: str) -> str:
    lines: list[str] = [
        "💼 **보유종목 요약**",
        "",
        "━━━━━━━━━━",
        "**💼 보유종목 관리**",
        "━━━━━━━━━━",
    ]
    lines.extend(_holding_summary(original_report))
    return "\n".join(lines).strip()


def build_daily_reports(logger: Logger = None, record_recommendations: bool = True) -> list[str]:
    reports = analyzer.build_daily_reports(logger=logger, record_recommendations=record_recommendations)
    if len(reports) != 2:
        return reports
    return [_slim_market_report(reports[0]), _slim_holdings_report(reports[1])]
