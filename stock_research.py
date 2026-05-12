from __future__ import annotations

from typing import Any

import analyzer


DATA_MISSING = "데이터 부족"


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not analyzer.math.isfinite(number):
        return None
    return number


def _info_number(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _safe_number(info.get(key))
        if number is not None:
            return number
    return None


def _short_text(value: Any, limit: int = 90) -> str:
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
        "news": [],
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

    try:
        raw_news = getattr(yf_ticker, "news", []) or []
        titles: list[str] = []
        for item in raw_news[:3]:
            content = item.get("content", item) if isinstance(item, dict) else {}
            title = ""
            if isinstance(content, dict):
                title = str(content.get("title") or content.get("summary") or "")
            if not title and isinstance(item, dict):
                title = str(item.get("title") or item.get("summary") or "")
            if title:
                titles.append(_short_text(title, 100))
        profile["news"] = titles
    except Exception:
        profile["news"] = []

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
        return "정량 지표상 우위 가능, 정성 검증 필요"
    if positive_fcf and (strong_margin or strong_roe):
        return "일부 우위 가능, 지속성 확인 필요"
    return "정량상 강한 해자 확인 부족"


def _market_valuation_view(valuation: dict[str, Any], financial: dict[str, Any]) -> str:
    per = valuation.get("per")
    growth = financial.get("revenue_growth") or financial.get("eps_growth")
    roe = financial.get("roe")
    if per is None or growth is None:
        return DATA_MISSING
    normalized_growth = growth * 100 if abs(growth) <= 2 else growth
    normalized_roe = roe * 100 if roe is not None and abs(roe) <= 2 else roe
    if per <= 15 and normalized_growth > 10:
        return "성장 대비 과소평가 가능"
    if per >= 35 and normalized_growth < 15:
        return "성장 대비 과대평가 가능"
    if normalized_roe is not None and normalized_roe >= 15 and per <= 25:
        return "품질 대비 중립~저평가 가능"
    return "중립 또는 판단 보류"


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


def _targets_text(analysis: analyzer.StockAnalysis) -> str:
    levels = analysis.target_analysis.levels
    if not levels:
        return analyzer.format_price_for_ticker(analysis.target_price, analysis.ticker)
    values = [analyzer.format_price_for_ticker(level.price, analysis.ticker) for level in levels[:3]]
    while len(values) < 3:
        values.append(DATA_MISSING)
    return f"1차 {values[0]} / 2차 {values[1]} / 최종 {values[2]}"


def _news_lines(analysis: analyzer.StockAnalysis, context: analyzer.AnalysisContext, profile: dict[str, Any]) -> list[str]:
    news = list(profile.get("news") or [])
    if news:
        return news[:2]
    try:
        related = analyzer.related_news_lines(analysis, context)
    except Exception:
        related = []
    return [line for line in related if line and line != "-"][:2] or [DATA_MISSING]


def _append_company_core(lines: list[str], profile: dict[str, Any], financial: dict[str, Any]) -> None:
    info = profile["info"]
    summary = _short_text(info.get("longBusinessSummary"), 110)
    revenue_source = "사업 설명 기준, 세그먼트 매출 데이터 부족" if summary != DATA_MISSING else DATA_MISSING
    growth = financial.get("revenue_growth") or financial.get("eps_growth")
    growth_text = f"매출/EPS 성장률 {_format_pct(growth)}" if growth is not None else DATA_MISSING
    lines.extend(analyzer.section("🏢 기업 핵심"))
    lines.append(f"주요 사업: {_bold_or_missing(summary)}")
    lines.append(f"실제 수익원: {_bold_or_missing(revenue_source)}")
    lines.append(f"성장 동력: {_bold_or_missing(growth_text)}")
    lines.append("")


def _append_industry_position(lines: list[str], profile: dict[str, Any], financial: dict[str, Any]) -> None:
    info = profile["info"]
    sector = str(info.get("sector") or "").strip()
    industry = str(info.get("industry") or "").strip()
    industry_text = " / ".join(part for part in (sector, industry) if part) or DATA_MISSING
    cycle_text = f"{industry_text}, 사이클 데이터 부족" if industry_text != DATA_MISSING else DATA_MISSING
    lines.extend(analyzer.section("🏭 산업/경쟁 위치"))
    lines.append(f"산업 사이클: {_bold_or_missing(cycle_text)}")
    lines.append(f"주요 경쟁사/진입장벽: {_bold_or_missing(DATA_MISSING)}")
    lines.append(f"Moat 평가: {_bold_or_missing(_moat_text(financial))}")
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
    lines.append(
        "현금흐름/재무상태: "
        + analyzer.bold(f"FCF {_format_money(financial.get('fcf'), currency)}, {debt_cash}")
    )
    lines.append(
        "수익성/질: "
        + analyzer.bold(
            f"ROE {_format_pct(financial.get('roe'))}, ROIC {_format_pct(financial.get('roic'))}, "
            f"{_quality_text(financial)}"
        )
    )
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
    lines.append(f"업종/과거 평균 대비: {analyzer.bold(DATA_MISSING)}")
    lines.append(f"성장률 대비: {analyzer.bold(valuation.get('burden') or DATA_MISSING)}")
    lines.append(f"좋은 기업 vs 좋은 주식: {analyzer.bold('좋은 기업이어도 가격이 비싸면 기대수익률은 낮아질 수 있음')}")
    lines.append("")


def _append_recent_results_news(
    lines: list[str],
    analysis: analyzer.StockAnalysis,
    context: analyzer.AnalysisContext,
    profile: dict[str, Any],
    financial: dict[str, Any],
) -> None:
    currency = financial.get("currency", "")
    quarter = (
        f"매출 {_format_money(financial.get('latest_quarter_revenue'), currency)}, "
        f"OPM {_format_pct(financial.get('latest_quarter_op_margin'))}, "
        f"NPM {_format_pct(financial.get('latest_quarter_net_margin'))}"
    )
    news = " / ".join(_news_lines(analysis, context, profile))
    lines.extend(analyzer.section("📰 최근 실적/뉴스"))
    lines.append(f"최근 분기: {analyzer.bold(quarter)}")
    lines.append(f"서프라이즈/가이던스: {analyzer.bold(DATA_MISSING)}")
    lines.append(f"핵심 뉴스: {analyzer.bold(news)}")
    lines.append("")


def _append_catalysts_risks(
    lines: list[str],
    analysis: analyzer.StockAnalysis,
    financial: dict[str, Any],
    valuation: dict[str, Any],
) -> None:
    catalysts: list[str] = []
    if analysis.themes:
        catalysts.append(f"테마 수급: {', '.join(analysis.themes[:2])}")
    if financial.get("revenue_growth") is not None and financial["revenue_growth"] > 0:
        catalysts.append(f"매출 성장 {_format_pct(financial['revenue_growth'])}")
    if analysis.timing_score >= 70:
        catalysts.append("기술적 타이밍 양호")
    risks = list(analysis.risk_bullets[:2])
    if "부담 높음" in str(valuation.get("burden")):
        risks.append("성장 대비 밸류 부담")
    if financial.get("debt") and financial.get("cash") and financial["debt"] > financial["cash"]:
        risks.append("부채가 현금보다 큼")

    lines.extend(analyzer.section("🚦 촉매와 리스크"))
    lines.append(f"상승 촉매: {_bold_or_missing(' / '.join(catalysts[:3]) or DATA_MISSING)}")
    lines.append(f"하락 리스크: {_bold_or_missing(' / '.join(risks[:3]) or DATA_MISSING)}")
    lines.append(f"시장 평가: {_bold_or_missing(_market_valuation_view(valuation, financial))}")
    lines.append("")


def _append_self_rebuttal(lines: list[str], analysis: analyzer.StockAnalysis, financial: dict[str, Any]) -> None:
    rebuttals = [
        "재무/뉴스 데이터가 부족하면 정성 판단이 빗나갈 수 있음",
        "진입구간 터치 전 목표가를 먼저 가면 추격매수 위험이 커짐",
    ]
    if financial.get("revenue_growth") is not None and financial["revenue_growth"] < 0:
        rebuttals.append("매출 둔화가 일시적이 아니라 구조적일 수 있음")
    elif analysis.timing_score >= 70:
        rebuttals.append("단기 과열 후 평균회귀가 먼저 나올 수 있음")
    else:
        rebuttals.append("기술적 약세가 예상보다 오래 지속될 수 있음")
    lines.extend(analyzer.section("🧭 자기반박"))
    for item in rebuttals[:3]:
        lines.append(f"* {item}")
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
    lines.append(f"목표가: {analyzer.bold(_targets_text(analysis))}")
    lines.append(f"확신도: {analyzer.bold(f'{confidence} / 100')}")


def stock_detail_report(query: str) -> str:
    analysis, context = analyzer.analyze_query_stock(query)
    if analysis.error:
        return analyzer.stock_detail_report(query)

    profile = _load_profile(analysis.ticker)
    financial = _financial_snapshot(profile)
    valuation = _valuation_snapshot(profile, financial)
    rsi = _safe_number(analysis.metrics.get("rsi"))
    volume_ratio = _safe_number(analysis.metrics.get("volume_ratio"))
    rsi_text = f"{rsi:.1f}" if rsi is not None else DATA_MISSING
    volume_text = f"{volume_ratio:.1f}배" if volume_ratio is not None else DATA_MISSING

    lines: list[str] = []
    lines.extend(analyzer.section("🔎 종목분석"))
    lines.append(f"종목명: {analyzer.bold(analysis.name)}")
    lines.append(f"티커: {analyzer.bold(analysis.ticker)}")
    lines.append(f"현재가: {analyzer.bold(analyzer.format_price_for_ticker(analysis.current_price, analysis.ticker))}")
    lines.append(f"등락률: {analyzer.bold(analyzer.format_pct(analysis.change_pct))}")
    lines.append(f"20일선 위치: {analyzer.bold(analyzer.format_pct(analysis.metrics.get('price_vs_ma20')))}")
    lines.append(f"60일선: {analyzer.bold(analyzer.format_price_for_ticker(analysis.metrics.get('ma60'), analysis.ticker))}")
    lines.append(f"RSI: {analyzer.bold(rsi_text)}")
    lines.append(f"거래량 변화: {analyzer.bold(volume_text)}")
    lines.append(f"퀀트 점수: {analyzer.bold(analysis.quant_score)}")
    lines.append(f"매매 타이밍 점수: {analyzer.bold(analysis.timing_score)}")
    lines.append(f"관련 테마: {analyzer.bold(', '.join(analysis.themes) if analysis.themes else '-')}")
    lines.append("")

    _append_technical_theme_basis(lines, analysis)
    _append_company_core(lines, profile, financial)
    _append_industry_position(lines, profile, financial)
    _append_financial_check(lines, financial)
    _append_valuation(lines, valuation)
    _append_recent_results_news(lines, analysis, context, profile, financial)
    _append_catalysts_risks(lines, analysis, financial, valuation)
    _append_self_rebuttal(lines, analysis, financial)
    _append_final_judgment(lines, analysis, valuation)
    return "\n".join(lines).strip()
