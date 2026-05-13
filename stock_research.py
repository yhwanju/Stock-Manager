from __future__ import annotations

import math
from typing import Any

import analyzer


DATA_MISSING = "데이터 부족"


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _info_number(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _safe_number(info.get(key))
        if number is not None:
            return number
    return None


def _short_text(value: Any, limit: int = 110) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if not text:
        return DATA_MISSING
    sentence_points = [pos for pos in (text.find("."), text.find("。"), text.find("다.")) if pos >= 20]
    if sentence_points:
        text = text[: min(sentence_points) + 1]
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _bold_or_missing(value: Any) -> str:
    text = str(value or "").strip()
    return analyzer.bold(text if text else DATA_MISSING)


def _format_pct(value: float | None) -> str:
    if value is None:
        return DATA_MISSING
    if abs(value) <= 2:
        value *= 100
    return f"{value:+.1f}%"


def _format_ratio(value: float | None, suffix: str = "배") -> str:
    if value is None or value <= 0:
        return DATA_MISSING
    return f"{value:.1f}{suffix}"


def _format_money(value: float | None, currency: str = "") -> str:
    if value is None:
        return DATA_MISSING
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    for divider, suffix in ((1_000_000_000_000, "T"), (1_000_000_000, "B"), (1_000_000, "M")):
        if absolute >= divider:
            return f"{sign}{absolute / divider:.1f}{suffix} {currency}".strip()
    return f"{value:,.0f} {currency}".strip()


def _load_profile(ticker: str) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "info": {},
        "financials": None,
        "quarterly_financials": None,
        "cashflow": None,
        "balance_sheet": None,
    }
    try:
        yf_ticker = analyzer.yf.Ticker(ticker)
    except Exception:
        return profile

    try:
        profile["info"] = dict(getattr(yf_ticker, "info", {}) or {})
    except Exception:
        profile["info"] = {}

    for key, attr in (
        ("financials", "financials"),
        ("quarterly_financials", "quarterly_financials"),
        ("cashflow", "cashflow"),
        ("balance_sheet", "balance_sheet"),
    ):
        try:
            profile[key] = getattr(yf_ticker, attr)
        except Exception:
            profile[key] = None
    return profile


def _row_value(frame: Any, names: tuple[str, ...], offset: int = 0) -> float | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    for name in names:
        if name not in frame.index:
            continue
        values = frame.loc[name].dropna()
        if len(values) > offset:
            return _safe_number(values.iloc[offset])
    return None


def _row_growth(frame: Any, names: tuple[str, ...]) -> float | None:
    latest = _row_value(frame, names, 0)
    previous = _row_value(frame, names, 1)
    if latest is None or previous is None or previous == 0:
        return None
    return ((latest / abs(previous)) - 1) * 100


def _margin(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * 100


def _financial_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    info = profile["info"]
    financials = profile["financials"]
    quarterly = profile["quarterly_financials"]
    cashflow = profile["cashflow"]
    balance = profile["balance_sheet"]
    currency = str(info.get("financialCurrency") or info.get("currency") or "")

    revenue = _row_value(financials, ("Total Revenue", "Operating Revenue"))
    operating_income = _row_value(financials, ("Operating Income",))
    net_income = _row_value(financials, ("Net Income", "Net Income Common Stockholders"))
    fcf = _row_value(cashflow, ("Free Cash Flow",))
    if fcf is None:
        operating_cashflow = _row_value(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"))
        capex = _row_value(cashflow, ("Capital Expenditure", "Capital Expenditures"))
        if operating_cashflow is not None and capex is not None:
            fcf = operating_cashflow + capex

    cash = _row_value(balance, ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"))
    debt = _row_value(balance, ("Total Debt", "Long Term Debt"))
    invested_capital = _row_value(balance, ("Invested Capital", "Total Capitalization"))
    latest_quarter_revenue = _row_value(quarterly, ("Total Revenue", "Operating Revenue"))
    latest_quarter_operating_income = _row_value(quarterly, ("Operating Income",))
    latest_quarter_net_income = _row_value(quarterly, ("Net Income", "Net Income Common Stockholders"))

    return {
        "currency": currency,
        "revenue_growth": _row_growth(financials, ("Total Revenue", "Operating Revenue")) or _info_number(info, "revenueGrowth"),
        "eps_growth": _info_number(info, "earningsGrowth", "earningsQuarterlyGrowth"),
        "operating_margin": _margin(operating_income, revenue) or _info_number(info, "operatingMargins"),
        "net_margin": _margin(net_income, revenue) or _info_number(info, "profitMargins"),
        "fcf": fcf or _info_number(info, "freeCashflow"),
        "cash": cash or _info_number(info, "totalCash"),
        "debt": debt or _info_number(info, "totalDebt"),
        "roe": _info_number(info, "returnOnEquity"),
        "roic": _margin(operating_income, invested_capital),
        "net_income": net_income,
        "latest_quarter_revenue": latest_quarter_revenue,
        "latest_quarter_op_margin": _margin(latest_quarter_operating_income, latest_quarter_revenue),
        "latest_quarter_net_margin": _margin(latest_quarter_net_income, latest_quarter_revenue),
    }


def _valuation_snapshot(profile: dict[str, Any], financial: dict[str, Any]) -> dict[str, Any]:
    info = profile["info"]
    pe = _info_number(info, "trailingPE", "forwardPE")
    growth = financial.get("revenue_growth") or financial.get("eps_growth")
    burden = DATA_MISSING
    if pe is not None and growth is not None:
        normalized_growth = growth * 100 if abs(growth) <= 2 else growth
        if normalized_growth <= 0 and pe >= 15:
            burden = "성장 둔화 대비 밸류 부담 높음"
        elif normalized_growth > 0:
            peg_like = pe / normalized_growth
            if peg_like >= 2:
                burden = "성장률 대비 부담 높음"
            elif peg_like <= 1:
                burden = "성장률 대비 부담 낮음"
            else:
                burden = "성장률 대비 중립"

    return {
        "per": pe,
        "pbr": _info_number(info, "priceToBook"),
        "psr": _info_number(info, "priceToSalesTrailing12Months"),
        "ev_ebitda": _info_number(info, "enterpriseToEbitda"),
        "burden": burden,
    }


def _quality_text(financial: dict[str, Any]) -> str:
    fcf = financial.get("fcf")
    net_income = financial.get("net_income")
    op_margin = financial.get("operating_margin")
    if fcf is None or net_income is None:
        return DATA_MISSING
    if fcf > 0 and net_income > 0 and fcf >= net_income * 0.7:
        return "순이익 대비 현금창출 양호"
    if net_income > 0 and fcf <= 0:
        return "이익은 있으나 FCF 전환 약함"
    if op_margin is not None and op_margin < 0:
        return "적자 구간, 실적 변동성 주의"
    return "혼재"


def _moat_text(financial: dict[str, Any]) -> str:
    op_margin = financial.get("operating_margin")
    roe = financial.get("roe")
    fcf = financial.get("fcf")
    if op_margin is None and roe is None and fcf is None:
        return DATA_MISSING
    strong_margin = op_margin is not None and op_margin >= 20
    strong_roe = roe is not None and (roe >= 0.15 if abs(roe) <= 2 else roe >= 15)
    positive_fcf = fcf is not None and fcf > 0
    if strong_margin and strong_roe and positive_fcf:
        return "정량 지표상 우위 가능, 지속성 확인 필요"
    if positive_fcf and (strong_margin or strong_roe):
        return "일부 우위 가능, 추가 검증 필요"
    return "정량상 강한 해자 확인 부족"


def _final_decision(analysis: analyzer.StockAnalysis, valuation: dict[str, Any]) -> str:
    price_vs_ma20 = analysis.metrics.get("price_vs_ma20", 0.0) or 0.0
    burden = str(valuation.get("burden") or "")
    if analysis.quant_score >= 80 and analysis.timing_score >= 75 and "부담 높음" not in burden:
        return "매수"
    if analysis.quant_score >= 65 and analysis.timing_score >= 55:
        return "분할매수"
    if analysis.quant_score < 40 or analysis.timing_score < 35 or price_vs_ma20 < -8:
        return "매도/비중축소"
    return "관망"


def _target_summary_lines(analysis: analyzer.StockAnalysis) -> list[str]:
    levels = analysis.target_analysis.levels
    labels = [
        ("🟢", "1차 목표가"),
        ("🟡", "2차 목표가"),
        ("🔴", "최종 목표가"),
    ]
    lines: list[str] = []
    for index, (emoji, label) in enumerate(labels):
        if len(levels) > index:
            price = levels[index].price
        else:
            price = analysis.target_price if index == 0 else None
        lines.append(f"{emoji} {label}: {analyzer.bold(analyzer.format_price_for_ticker(price, analysis.ticker))}")
    return lines


def _append_quick_header(lines: list[str], analysis: analyzer.StockAnalysis) -> None:
    rsi = _safe_number(analysis.metrics.get("rsi"))
    volume_ratio = _safe_number(analysis.metrics.get("volume_ratio"))
    rsi_text = f"{rsi:.1f}" if rsi is not None else DATA_MISSING
    volume_text = f"{volume_ratio:.1f}배" if volume_ratio is not None else DATA_MISSING
    lines.extend(analyzer.section("🔎 종목분석"))
    lines.append(f"종목명: {analyzer.bold(analysis.name)}")
    lines.append(f"티커: {analyzer.bold(analysis.ticker)}")
    lines.append(f"현재가: {analyzer.bold(analyzer.format_price_for_ticker(analysis.current_price, analysis.ticker))}")
    lines.append(f"등락률: {analyzer.bold(analyzer.format_pct(analysis.change_pct))}")
    lines.append(f"RSI: {analyzer.bold(rsi_text)}")
    lines.append(f"거래량 변화: {analyzer.bold(volume_text)}")
    lines.append(f"퀀트/타이밍: {analyzer.bold(f'{analysis.quant_score} / {analysis.timing_score}')}")
    lines.append(f"관련 테마: {analyzer.bold(', '.join(analysis.themes) if analysis.themes else '-')}")
    lines.append("")


def _append_technical_theme_basis(lines: list[str], analysis: analyzer.StockAnalysis) -> None:
    lines.extend(analyzer.section("📌 기술/테마 근거"))
    for reason in analysis.reason_bullets[:3]:
        lines.append(f"* {reason}")
    if not analysis.reason_bullets:
        lines.append(f"* {DATA_MISSING}")
    lines.append("")


def _append_final_judgment(lines: list[str], analysis: analyzer.StockAnalysis, valuation: dict[str, Any]) -> None:
    confidence = analysis.target_analysis.confidence_score or analysis.target_analysis.condition_score or analysis.composite_score
    lines.extend(analyzer.section("✅ 최종 판단"))
    lines.append(f"판단: {analyzer.bold(_final_decision(analysis, valuation))}")
    lines.append(f"진입구간: {analyzer.bold(analysis.entry_zone)}")
    lines.append(f"손절 기준: {analyzer.bold(analyzer.format_price_for_ticker(analysis.stop_price, analysis.ticker))}")
    lines.append("목표가:")
    lines.extend(_target_summary_lines(analysis))
    lines.append(f"확신도: {analyzer.bold(f'{confidence} / 100')}")


def _append_company_core(lines: list[str], profile: dict[str, Any], financial: dict[str, Any]) -> None:
    info = profile["info"]
    summary = _short_text(info.get("longBusinessSummary"), 110)
    growth = financial.get("revenue_growth") or financial.get("eps_growth")
    growth_text = f"매출/EPS 성장률 {_format_pct(growth)}" if growth is not None else DATA_MISSING
    lines.extend(analyzer.section("🏢 기업 핵심"))
    lines.append(f"주요 사업: {_bold_or_missing(summary)}")
    lines.append(f"성장 동력: {_bold_or_missing(growth_text)}")
    lines.append("")


def _append_financial_check(lines: list[str], financial: dict[str, Any]) -> None:
    currency = financial.get("currency", "")
    cash = financial.get("cash")
    debt = financial.get("debt")
    debt_cash = DATA_MISSING
    if cash is not None or debt is not None:
        debt_cash = f"현금 {_format_money(cash, currency)} / 부채 {_format_money(debt, currency)}"
    lines.extend(analyzer.section("💵 재무 체크"))
    lines.append(
        "성장/마진: "
        + analyzer.bold(
            f"매출 {_format_pct(financial.get('revenue_growth'))}, "
            f"OPM {_format_pct(financial.get('operating_margin'))}, "
            f"NPM {_format_pct(financial.get('net_margin'))}, EPS {_format_pct(financial.get('eps_growth'))}"
        )
    )
    lines.append("현금흐름/재무상태: " + analyzer.bold(f"FCF {_format_money(financial.get('fcf'), currency)}, {debt_cash}"))
    lines.append(
        "수익성/질: "
        + analyzer.bold(
            f"ROE {_format_pct(financial.get('roe'))}, ROIC {_format_pct(financial.get('roic'))}, "
            f"{_quality_text(financial)}"
        )
    )
    lines.append(f"Moat 평가: {analyzer.bold(_moat_text(financial))}")
    lines.append("")


def _append_valuation(lines: list[str], valuation: dict[str, Any]) -> None:
    lines.extend(analyzer.section("⚖️ 밸류에이션"))
    lines.append(
        "멀티플: "
        + analyzer.bold(
            f"PER {_format_ratio(valuation.get('per'))}, "
            f"PBR {_format_ratio(valuation.get('pbr'))}, "
            f"PSR {_format_ratio(valuation.get('psr'))}, "
            f"EV/EBITDA {_format_ratio(valuation.get('ev_ebitda'))}"
        )
    )
    lines.append(f"성장률 대비: {analyzer.bold(valuation.get('burden') or DATA_MISSING)}")
    lines.append(f"가격 관점: {analyzer.bold('기업은 좋아도 현재 주가 부담이 크면 기대수익률은 제한될 수 있음')}")
    lines.append("")


def _append_recent_results(lines: list[str], financial: dict[str, Any]) -> None:
    currency = financial.get("currency", "")
    quarter = (
        f"매출 {_format_money(financial.get('latest_quarter_revenue'), currency)}, "
        f"OPM {_format_pct(financial.get('latest_quarter_op_margin'))}, "
        f"NPM {_format_pct(financial.get('latest_quarter_net_margin'))}"
    )
    lines.extend(analyzer.section("📊 최근 실적"))
    lines.append(f"최근 분기: {analyzer.bold(quarter)}")
    lines.append(f"가이던스: {analyzer.bold(DATA_MISSING)}")
    lines.append("")


def _append_self_rebuttal(lines: list[str], analysis: analyzer.StockAnalysis, financial: dict[str, Any]) -> None:
    rebuttals = [
        "재무 데이터가 부족하면 기업 체력 판단이 보수적일 수 있음",
        "눌림 없이 급등하면 추격매수 리스크 커질 수 있음",
    ]
    if financial.get("revenue_growth") is not None and financial["revenue_growth"] < 0:
        rebuttals.append("매출 둔화가 일시적이 아니라 구조적일 가능성 있음")
    elif analysis.timing_score >= 70:
        rebuttals.append("단기 과열 후 조정이 먼저 나올 수 있음")
    else:
        rebuttals.append("생각보다 조정 기간이 길어질 가능성 있음")
    lines.extend(analyzer.section("🧭 자기반박"))
    for item in rebuttals[:3]:
        lines.append(f"* {item}")
    lines.append("")


def stock_detail_report(query: str) -> str:
    analysis, _ = analyzer.analyze_query_stock(query)
    if analysis.error:
        return analyzer.stock_detail_report(query)

    lines: list[str] = []
    _append_quick_header(lines, analysis)
    _append_technical_theme_basis(lines, analysis)
    _append_final_judgment(lines, analysis, {})
    return "\n".join(lines).strip()


def stock_deep_detail_report(query: str) -> str:
    analysis, _ = analyzer.analyze_query_stock(query)
    if analysis.error:
        return analyzer.stock_detail_report(query)

    profile = _load_profile(analysis.ticker)
    financial = _financial_snapshot(profile)
    valuation = _valuation_snapshot(profile, financial)

    lines: list[str] = []
    lines.extend(analyzer.section("🔬 종목세부분석"))
    lines.append(f"종목명: {analyzer.bold(analysis.name)}")
    lines.append(f"티커: {analyzer.bold(analysis.ticker)}")
    lines.append(f"현재가: {analyzer.bold(analyzer.format_price_for_ticker(analysis.current_price, analysis.ticker))}")
    lines.append("")
    _append_company_core(lines, profile, financial)
    _append_financial_check(lines, financial)
    _append_valuation(lines, valuation)
    _append_recent_results(lines, financial)
    _append_self_rebuttal(lines, analysis, financial)
    return "\n".join(lines).strip()
