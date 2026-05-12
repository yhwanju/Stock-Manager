from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Callable

import analyzer
import storage
from config import KST


Logger = Callable[[str], None] | None

RECOMMENDATION_STATES = [
    "PENDING",
    "ENTRY_TRIGGERED",
    "PARTIAL_SUCCESS",
    "SUCCESS",
    "FAIL",
    "NO_ENTRY",
]
NO_ENTRY_AFTER_DAYS = 20


def _log(logger: Logger, message: str) -> None:
    if logger:
        logger(message)


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _recommendation_datetime(item: dict[str, Any]) -> datetime | None:
    raw_date = str(item.get("date", "") or "").replace(" KST", "").strip()
    if not raw_date:
        return None
    for parser in (
        lambda value: datetime.fromisoformat(value),
        lambda value: datetime.strptime(value[:10], "%Y-%m-%d"),
    ):
        try:
            return parser(raw_date)
        except ValueError:
            continue
    return None


def _index_date(value: Any):
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value[:10]).date()
        except ValueError:
            return None
    return None


def _history_from_recommendation(ticker: str, recommendation_dt: datetime | None):
    try:
        history = analyzer.fetch_history(ticker)
    except Exception as exc:
        return None, str(exc)

    if history.empty:
        return None, "시세 데이터가 비어 있습니다."

    if recommendation_dt is None:
        return history, None

    start_date = recommendation_dt.date()
    try:
        mask = []
        for index in history.index:
            index_date = _index_date(index)
            mask.append(index_date is not None and index_date >= start_date)
        filtered = history.loc[mask]
    except Exception:
        filtered = history
    return filtered, None


def _history_latest_close(history) -> float | None:
    if history is None or history.empty or "Close" not in history.columns:
        return None
    close = history["Close"].dropna()
    if close.empty:
        return None
    return _safe_float(close.iloc[-1])


def _entry_bounds(item: dict[str, Any]) -> tuple[float | None, float | None]:
    entry_low = _safe_float(item.get("entry_low"))
    entry_high = _safe_float(item.get("entry_high"))
    if entry_low is None or entry_high is None:
        return None, None
    if entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low
    return entry_low, entry_high


def _entry_reference_price(item: dict[str, Any], entry_low: float | None, entry_high: float | None) -> float | None:
    explicit_reference = _safe_float(item.get("entry_reference_price"))
    if explicit_reference is not None:
        return explicit_reference
    if entry_low is not None and entry_high is not None:
        return (entry_low + entry_high) / 2
    return _safe_float(item.get("price"))


def _entry_fields_from_analysis(item: analyzer.StockAnalysis) -> tuple[float | None, float | None, float | None]:
    price = _safe_float(item.current_price)
    if price is None:
        return None, None, None
    ma5 = _safe_float(item.metrics.get("ma5")) or price
    entry_low = min(price * 0.985, ma5 * 0.995)
    entry_high = price * (1.015 if item.timing_score >= 70 else 1.0)
    return entry_low, entry_high, (entry_low + entry_high) / 2


def _recommendation_state_from_history(
    item: dict[str, Any],
    history,
    recommendation_dt: datetime | None,
    entry_low: float | None,
    entry_high: float | None,
) -> dict[str, Any]:
    target_1 = _safe_float(item.get("target_1")) or _safe_float(item.get("target_price"))
    target_2 = _safe_float(item.get("target_2"))
    target_final = _safe_float(item.get("target_final")) or target_2 or _safe_float(item.get("target_price"))
    stop_price = _safe_float(item.get("stop_price"))
    has_entry_zone = entry_low is not None and entry_high is not None
    entry_triggered = not has_entry_zone
    entry_triggered_at = ""
    prediction_result = "PENDING"
    hit_target_1 = False
    hit_target_2 = False
    hit_target_final = False
    hit_stop_loss = False
    actual_best_target = ""

    if history is not None and not history.empty:
        for index, row in history.iterrows():
            high = _safe_float(row.get("High")) or _safe_float(row.get("Close"))
            low = _safe_float(row.get("Low")) or _safe_float(row.get("Close"))
            if high is None or low is None:
                continue

            if not entry_triggered:
                entry_triggered = bool(low <= entry_high and high >= entry_low)
                if entry_triggered:
                    index_date = _index_date(index)
                    entry_triggered_at = str(index_date or index)
                    prediction_result = "ENTRY_TRIGGERED"
                else:
                    continue

            if stop_price and low <= stop_price and not (hit_target_1 or hit_target_2 or hit_target_final):
                hit_stop_loss = True
                prediction_result = "FAIL"
                break
            if target_final and high >= target_final:
                hit_target_final = True
                actual_best_target = "최종 목표가"
                prediction_result = "SUCCESS"
                break
            if target_2 and high >= target_2:
                hit_target_2 = True
                actual_best_target = "2차 목표가"
                prediction_result = "PARTIAL_SUCCESS"
            if target_1 and high >= target_1:
                hit_target_1 = True
                actual_best_target = actual_best_target or "1차 목표가"
                prediction_result = "PARTIAL_SUCCESS"

    if has_entry_zone and not entry_triggered:
        days_since = 0
        if recommendation_dt is not None:
            days_since = (datetime.now(KST).date() - recommendation_dt.date()).days
        prediction_result = "NO_ENTRY" if days_since >= NO_ENTRY_AFTER_DAYS else "PENDING"
    elif entry_triggered and prediction_result == "PENDING":
        prediction_result = "ENTRY_TRIGGERED"

    return {
        "entry_triggered": entry_triggered,
        "entry_triggered_at": entry_triggered_at,
        "hit_target_1": hit_target_1,
        "hit_target_2": hit_target_2,
        "hit_target_final": hit_target_final,
        "hit_stop_loss": hit_stop_loss,
        "actual_best_target": actual_best_target,
        "prediction_result": prediction_result,
    }


def _recommendation_assessment(item: dict[str, Any]) -> dict[str, Any]:
    ticker = str(item.get("ticker", "") or "")
    entry_low, entry_high = _entry_bounds(item)
    entry_reference_price = _entry_reference_price(item, entry_low, entry_high)
    if not ticker or entry_reference_price is None:
        return {"entry_price": None, "return_pct": None, "error": "추천 당시 기준가 없음"}

    recommendation_dt = _recommendation_datetime(item)
    history, history_error = _history_from_recommendation(ticker, recommendation_dt)
    current_price_from_history = _history_latest_close(history)
    analysis = analyzer.analyze_stock(
        {
            "name": str(item.get("name", ticker) or ticker),
            "ticker": ticker,
            "themes": item.get("themes", []) if isinstance(item.get("themes", []), list) else [],
        },
        [],
        str(item.get("market_state", "횡보장") or "횡보장"),
    )
    current_price = _safe_float(analysis.current_price) or current_price_from_history
    if current_price is None:
        return {
            "entry_price": entry_reference_price,
            "entry_reference_price": entry_reference_price,
            "return_pct": None,
            "current_price": None,
            "error": analysis.error or history_error or "현재가 조회 실패",
            "prediction_result": item.get("prediction_result", "PENDING") or "PENDING",
        }

    return_pct = ((current_price / entry_reference_price) - 1) * 100
    state = _recommendation_state_from_history(item, history, recommendation_dt, entry_low, entry_high)
    confidence_score = int(
        item.get("confidence_score")
        or round(float(item.get("quant_score", 0) or 0) * 0.55 + float(item.get("timing_score", 0) or 0) * 0.45)
    )
    return {
        "entry_price": entry_reference_price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_reference_price": entry_reference_price,
        "return_pct": return_pct,
        "current_price": current_price,
        "error": None,
        **state,
        "confidence_score": confidence_score,
    }


def _refresh_recommendation_history(
    history: list[dict[str, Any]],
    logger: Logger = None,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]], int]:
    assessed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    changed = False
    skipped = 0
    for item in history:
        assessment = _recommendation_assessment(item)
        if assessment.get("return_pct") is None:
            skipped += 1
            continue
        assessed.append((item, assessment))
        for key in (
            "entry_low",
            "entry_high",
            "entry_reference_price",
            "entry_triggered",
            "entry_triggered_at",
            "return_pct",
            "hit_target_1",
            "hit_target_2",
            "hit_target_final",
            "hit_stop_loss",
            "actual_best_target",
            "prediction_result",
            "confidence_score",
        ):
            if item.get(key) != assessment.get(key):
                item[key] = assessment.get(key)
                changed = True
    if changed:
        storage.save_recommendation_history(history, logger=logger)
    return history, assessed, skipped


def _result_rate(assessed: list[tuple[dict[str, Any], dict[str, Any]]], result: str) -> float:
    if not assessed:
        return 0.0
    count = sum(1 for _, assessment in assessed if assessment.get("prediction_result") == result)
    return count / len(assessed) * 100


def _hit_rate(assessed: list[tuple[dict[str, Any], dict[str, Any]]], key: str) -> float:
    if not assessed:
        return 0.0
    count = sum(1 for _, assessment in assessed if assessment.get(key))
    return count / len(assessed) * 100


def _append_state_counts(lines: list[str], assessed: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    counts = Counter(str(assessment.get("prediction_result", "PENDING") or "PENDING") for _, assessment in assessed)
    total = len(assessed) or 1
    lines.append("상태별 현황:")
    for state in RECOMMENDATION_STATES:
        count = counts.get(state, 0)
        lines.append(f"* {state}: **{count}건 / {count / total * 100:.1f}%**")


def _recommendation_grade(item: dict[str, Any]) -> str:
    score = int(
        item.get("confidence_score")
        or round(float(item.get("quant_score", 0) or 0) * 0.55 + float(item.get("timing_score", 0) or 0) * 0.45)
    )
    if score >= 80:
        return "S"
    if score >= 65:
        return "A"
    return "B"


def _pattern_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "없음"
    markets = Counter(str(item.get("market_state", "-")) for item in items)
    themes: Counter[str] = Counter()
    for item in items:
        item_themes = item.get("themes", [])
        if not isinstance(item_themes, list):
            item_themes = []
        for theme in item_themes:
            themes[str(theme)] += 1
    market_label = markets.most_common(1)[0][0] if markets else "-"
    theme_label = themes.most_common(1)[0][0] if themes else "미분류"
    return f"{market_label} / {theme_label}"


def recommendation_performance(logger: Logger = None) -> str:
    history = storage.load_recommendation_history(logger=logger)
    lines = analyzer.section("📈 성과추적")
    if not history:
        lines.append("추천이력 없음")
        return "\n".join(lines).strip()

    _, assessed, skipped = _refresh_recommendation_history(history, logger=logger)
    recent_assessed = list(reversed(assessed))[:30]
    lines.append("최근 추천 성과:")
    lines.append(f"* 성공률: **{_result_rate(recent_assessed, 'SUCCESS'):.1f}%**")
    lines.append(f"* 부분성공률: **{_result_rate(recent_assessed, 'PARTIAL_SUCCESS'):.1f}%**")
    lines.append(f"* 진입대기율: **{_result_rate(recent_assessed, 'ENTRY_TRIGGERED'):.1f}%**")
    lines.append(f"* 실패율: **{_result_rate(recent_assessed, 'FAIL'):.1f}%**")
    lines.append(f"* 미진입률: **{_result_rate(recent_assessed, 'NO_ENTRY'):.1f}%**")
    lines.append(f"* 1차 목표가 적중률: **{_hit_rate(recent_assessed, 'hit_target_1'):.1f}%**")
    lines.append(f"* 손절률: **{_hit_rate(recent_assessed, 'hit_stop_loss'):.1f}%**")
    if skipped:
        lines.append(f"* 조회 제외: **{skipped}건**")
    lines.append("")
    _append_state_counts(lines, recent_assessed)
    lines.append("")
    lines.append("기준: **최근 추천 10건**")
    lines.append("")
    for item, assessment in list(reversed(assessed))[:10]:
        ticker = str(item.get("ticker", "") or "")
        entry_price = assessment.get("entry_price")
        return_pct = assessment.get("return_pct")
        error = assessment.get("error")
        lines.append(f"종목명: **{item.get('name', '-')}**")
        lines.append(f"추천일: **{item.get('date', '-')}**")
        lines.append(f"액션: **{item.get('action', '-')}**")
        lines.append(f"판정: **{assessment.get('prediction_result', '-')}**")
        lines.append(f"신뢰도: **{assessment.get('confidence_score', item.get('confidence_score', '-'))} / 100**")
        if entry_price:
            lines.append(f"진입 기준가: **{analyzer.format_price_for_ticker(entry_price, ticker)}**")
        if assessment.get("entry_low") and assessment.get("entry_high"):
            entry_zone = (
                f"{analyzer.format_price_for_ticker(assessment.get('entry_low'), ticker)} ~ "
                f"{analyzer.format_price_for_ticker(assessment.get('entry_high'), ticker)}"
            )
            lines.append(f"진입구간: **{entry_zone}**")
        if assessment.get("entry_triggered_at"):
            lines.append(f"진입 터치일: **{assessment.get('entry_triggered_at')}**")
        if return_pct is not None:
            lines.append(f"현재 성과: **{analyzer.format_pct(return_pct)}**")
        else:
            lines.append("현재 성과: **조회불가**")
            if error:
                lines.append(f"사유: **{error}**")
        lines.append("")
    return "\n".join(lines).strip()


def algorithm_performance(logger: Logger = None) -> str:
    history = storage.load_recommendation_history(logger=logger)
    lines = analyzer.section("📊 알고리즘성과")
    if not history:
        lines.append("추천이력 없음")
        return "\n".join(lines).strip()

    _, assessed, skipped = _refresh_recommendation_history(history, logger=logger)
    recent = list(reversed(assessed))[:30]
    if not recent:
        lines.append("분석 가능 이력: **0건**")
        lines.append(f"조회 제외: **{skipped}건**")
        return "\n".join(lines).strip()

    returns = [float(assessment.get("return_pct", 0) or 0) for _, assessment in recent]
    wins = [value for value in returns if value > 0]
    avg_return = sum(returns) / len(returns)
    win_rate = len(wins) / len(returns) * 100
    best_item, best_assessment = max(recent, key=lambda pair: float(pair[1].get("return_pct", 0) or 0))
    worst_item, worst_assessment = min(recent, key=lambda pair: float(pair[1].get("return_pct", 0) or 0))
    best_return = float(best_assessment.get("return_pct", 0) or 0)
    worst_return = float(worst_assessment.get("return_pct", 0) or 0)

    lines.append("분석 기준: **최근 최대 30건**")
    lines.append(f"분석 가능 이력: **{len(recent)}건**")
    lines.append(f"승률: **{win_rate:.1f}%**")
    lines.append(f"평균 성과: **{analyzer.format_pct(avg_return)}**")
    lines.append(f"1차 목표가 적중률: **{_hit_rate(recent, 'hit_target_1'):.1f}%**")
    lines.append("")
    _append_state_counts(lines, recent)
    lines.append("")

    grade_groups: dict[str, list[float]] = {"S": [], "A": [], "B": []}
    grade_wins: dict[str, int] = {"S": 0, "A": 0, "B": 0}
    for item, assessment in recent:
        grade = _recommendation_grade(item)
        return_pct = float(assessment.get("return_pct", 0) or 0)
        grade_groups[grade].append(return_pct)
        if return_pct > 0:
            grade_wins[grade] += 1

    lines.append("S/A/B 등급별 승률:")
    for grade in ("S", "A", "B"):
        values = grade_groups[grade]
        rate = grade_wins[grade] / len(values) * 100 if values else 0.0
        avg = sum(values) / len(values) if values else 0.0
        lines.append(f"* {grade}: **{rate:.1f}% / 평균 {analyzer.format_pct(avg)}**")
    lines.append("")
    lines.append(f"최고 성과: **{best_item.get('name', '-')} / {analyzer.format_pct(best_return)}**")
    lines.append(f"최저 성과: **{worst_item.get('name', '-')} / {analyzer.format_pct(worst_return)}**")
    success_items = [item for item, assessment in recent if assessment.get("prediction_result") in {"SUCCESS", "PARTIAL_SUCCESS"}]
    entry_items = [item for item, assessment in recent if assessment.get("prediction_result") == "ENTRY_TRIGGERED"]
    fail_items = [item for item, assessment in recent if assessment.get("prediction_result") == "FAIL"]
    no_entry_items = [item for item, assessment in recent if assessment.get("prediction_result") == "NO_ENTRY"]
    lines.append(f"최근 성공 패턴: **{_pattern_summary(success_items)}**")
    lines.append(f"최근 진입완료 대기 패턴: **{_pattern_summary(entry_items)}**")
    lines.append(f"최근 실패 패턴: **{_pattern_summary(fail_items)}**")
    lines.append(f"최근 미진입 패턴: **{_pattern_summary(no_entry_items)}**")
    if skipped:
        lines.append("")
        lines.append(f"조회 제외: **{skipped}건**")
    return "\n".join(lines).strip()


def analysis_performance(logger: Logger = None) -> str:
    report = algorithm_performance(logger=logger)
    return report.replace("**📊 알고리즘성과**", "**📊 분석성과**", 1)


def add_test_recommendation_history(logger: Logger = None) -> str:
    now = datetime.now(KST)
    ticker = "NVDA"
    name = "엔비디아"
    themes = ["AI", "반도체"]
    analysis = analyzer.analyze_stock(
        {"name": name, "ticker": ticker, "themes": themes},
        [],
        "횡보장",
    )
    current_price = _safe_float(analysis.current_price) or 100.0
    entry_low = round(current_price * 0.90, 2)
    entry_high = round(current_price * 0.92, 2)
    entry_reference_price = round((entry_low + entry_high) / 2, 2)
    target_1 = round(entry_reference_price * 1.08, 2)
    target_2 = round(entry_reference_price * 1.15, 2)
    target_final = round(entry_reference_price * 1.25, 2)
    stop_price = round(entry_reference_price * 0.92, 2)
    history = storage.load_recommendation_history(logger=logger)
    item = {
        "recommendation_id": f"test-{now:%Y%m%d%H%M%S}-{ticker}",
        "date": f"{now:%Y-%m-%d %H:%M:%S} KST",
        "name": name,
        "ticker": ticker,
        "price": current_price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_reference_price": entry_reference_price,
        "entry_zone": (
            f"{analyzer.format_price_for_ticker(entry_low, ticker)} ~ "
            f"{analyzer.format_price_for_ticker(entry_high, ticker)}"
        ),
        "action": "테스트",
        "quant_score": 75,
        "timing_score": 70,
        "market_state": "횡보장",
        "theme_strength": 80,
        "confidence_score": 73,
        "predicted_best_target": "1차 목표가",
        "actual_best_target": "",
        "target_1": target_1,
        "target_2": target_2,
        "target_final": target_final,
        "target_price": target_1,
        "stop_price": stop_price,
        "entry_triggered": False,
        "entry_triggered_at": "",
        "hit_target_1": False,
        "hit_target_2": False,
        "hit_target_final": False,
        "hit_stop_loss": False,
        "prediction_result": "PENDING",
        "themes": themes,
        "memo": "test_recommendation_history",
    }
    history.append(item)
    storage.save_recommendation_history(history, logger=logger)

    lines = analyzer.section("🧪 추천이력 테스트 추가")
    lines.append("테스트용 추천이력 1건을 저장했습니다.")
    lines.append(f"종목명: **{name} ({ticker})**")
    lines.append(f"진입구간: **{item['entry_zone']}**")
    lines.append(f"진입 기준가: **{analyzer.format_price_for_ticker(entry_reference_price, ticker)}**")
    lines.append(f"1차 목표가: **{analyzer.format_price_for_ticker(target_1, ticker)}**")
    lines.append(f"2차 목표가: **{analyzer.format_price_for_ticker(target_2, ticker)}**")
    lines.append(f"최종 목표가: **{analyzer.format_price_for_ticker(target_final, ticker)}**")
    lines.append(f"손절가: **{analyzer.format_price_for_ticker(stop_price, ticker)}**")
    lines.append("prediction_result: **PENDING**")
    lines.append("")
    lines.append("조회 가능 명령어: **/성과추적, /알고리즘성과, /분석성과**")
    return "\n".join(lines).strip()


def record_recommendation_history_with_entry_refs(
    market: analyzer.MarketSummary,
    recommendations: list[analyzer.StockAnalysis],
    strong_themes: list[str] | None = None,
    logger: Logger = None,
) -> None:
    if not recommendations:
        _log(logger, "추천이력 저장 스킵: 추천 종목 없음")
        return

    try:
        now = datetime.now(KST)
        today = f"{now:%Y-%m-%d}"
        history = storage.load_recommendation_history(logger=logger)
        existing_keys = {(str(item.get("date", ""))[:10], str(item.get("ticker", ""))) for item in history}
        added = 0
        strong_theme_keys = {analyzer.normalize_text(theme) for theme in (strong_themes or [])}
        for item in recommendations:
            key = (today, item.ticker)
            if key in existing_keys:
                continue
            levels = item.target_analysis.levels
            target_1 = levels[0].price if len(levels) >= 1 else item.target_price
            target_2 = levels[1].price if len(levels) >= 2 else item.target_price
            target_final = levels[2].price if len(levels) >= 3 else item.target_price
            entry_low, entry_high, entry_reference_price = _entry_fields_from_analysis(item)
            confidence_score = item.target_analysis.confidence_score or item.target_analysis.condition_score or item.composite_score
            matched_theme_count = sum(1 for theme in item.themes if analyzer.normalize_text(theme) in strong_theme_keys)
            theme_strength = analyzer.clamp((matched_theme_count * 35) + (10 if item.themes else 0) + (confidence_score * 0.35))
            history.append(
                {
                    "recommendation_id": f"{today}-{item.ticker}",
                    "date": f"{now:%Y-%m-%d %H:%M:%S} KST",
                    "name": item.name,
                    "ticker": item.ticker,
                    "price": item.current_price,
                    "entry_low": entry_low,
                    "entry_high": entry_high,
                    "entry_reference_price": entry_reference_price,
                    "entry_zone": item.entry_zone,
                    "action": item.final_action,
                    "quant_score": item.quant_score,
                    "timing_score": item.timing_score,
                    "market_state": market.state,
                    "theme_strength": theme_strength,
                    "confidence_score": confidence_score,
                    "predicted_best_target": item.target_analysis.most_realistic_label,
                    "actual_best_target": "",
                    "target_1": target_1,
                    "target_2": target_2,
                    "target_final": target_final,
                    "target_price": item.target_price,
                    "stop_price": item.stop_price,
                    "hit_target_1": False,
                    "hit_target_2": False,
                    "hit_target_final": False,
                    "hit_stop_loss": False,
                    "prediction_result": "PENDING",
                    "themes": item.themes,
                    "memo": "daily_report_top3",
                }
            )
            added += 1

        if not added:
            _log(logger, "추천이력 저장 스킵: 오늘 추천이력 이미 존재")
            return
        storage.save_recommendation_history(history, logger=logger)
        _log(logger, f"추천이력 저장 성공: {added}건")
    except Exception as exc:
        _log(logger, f"추천이력 저장 실패: {exc}")


def patch_analyzer_history_recorder() -> None:
    analyzer.record_recommendation_history = record_recommendation_history_with_entry_refs
