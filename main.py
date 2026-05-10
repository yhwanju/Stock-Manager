from __future__ import annotations

import argparse
import os
from datetime import datetime

import requests

from analyzer import build_daily_reports
from config import DISCORD_CONTENT_LIMIT, KST, WEBHOOK_ENV_NAME
import storage


def log(message: str) -> None:
    print(f"[stock-manager] {message}", flush=True)


def split_discord_message(report: str, limit: int = DISCORD_CONTENT_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""

    for block in report.split("\n\n"):
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(block) <= limit:
            current = block
            continue

        for line in block.splitlines():
            candidate_line = f"{current}\n{line}".strip() if current else line
            if len(candidate_line) > limit and current:
                chunks.append(current)
                current = line
            else:
                current = candidate_line

    if current:
        chunks.append(current)

    if len(chunks) <= 1:
        return chunks

    return [f"[{index}/{len(chunks)}]\n{chunk}" for index, chunk in enumerate(chunks, start=1)]


def send_discord_message(message_name: str, content: str, webhook_url: str) -> None:
    chunks = split_discord_message(content)
    if len(chunks) > 1:
        log(f"{message_name} 메시지가 길어 {len(chunks)}개로 나누어 전송합니다.")

    for index, chunk in enumerate(chunks, start=1):
        response = requests.post(
            webhook_url,
            json={
                "content": chunk,
                "allowed_mentions": {"parse": []},
            },
            timeout=20,
        )
        if response.status_code >= 400:
            log(f"{message_name} Discord 발송 실패: HTTP {response.status_code} {response.text}")
            raise RuntimeError(f"{message_name} Discord 발송 실패")

        part = f" ({index}/{len(chunks)})" if len(chunks) > 1 else ""
        log(f"{message_name} Discord 발송 성공{part}: {len(chunk)}자")


def send_to_discord(reports: list[str], webhook_url: str) -> None:
    if len(reports) != 2:
        raise ValueError(f"Discord 메시지는 2개여야 합니다. 현재 {len(reports)}개입니다.")

    send_discord_message("메시지1", reports[0], webhook_url)
    send_discord_message("메시지2", reports[1], webhook_url)


def is_weekend_kst(now: datetime) -> bool:
    return now.weekday() >= 5


def should_skip_for_weekend(now: datetime, event_name: str, force_weekend: bool) -> bool:
    if force_weekend:
        return False
    return event_name == "schedule" and is_weekend_kst(now)


def main() -> int:
    parser = argparse.ArgumentParser(description="데일리 주식관리 리포트 생성 및 Discord 발송")
    parser.add_argument("--dry-run", action="store_true", help="Discord 전송 없이 리포트만 출력합니다.")
    parser.add_argument("--force-weekend", action="store_true", help="주말에도 강제로 실행합니다.")
    args = parser.parse_args()

    now = datetime.now(KST)
    dry_run = args.dry_run or os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}
    event_name = os.getenv("GITHUB_EVENT_NAME", "local")

    log(f"실행 이벤트: {event_name}")
    log(f"현재 시각: {now:%Y-%m-%d %H:%M:%S} KST")
    storage.run_daily_backup_if_due(logger=log)

    if should_skip_for_weekend(now, event_name, args.force_weekend):
        log(f"발송 스킵: schedule 실행이고 {now:%Y-%m-%d} KST가 주말입니다.")
        return 0
    if event_name == "workflow_dispatch":
        log("workflow_dispatch 수동 실행: 주말 체크를 건너뛰고 발송을 진행합니다.")
    elif args.force_weekend:
        log("--force-weekend 옵션 사용: 주말 체크를 건너뛰고 진행합니다.")

    webhook_url = os.getenv(WEBHOOK_ENV_NAME)
    if not dry_run and not webhook_url:
        log(f"Discord 발송 실패: {WEBHOOK_ENV_NAME} 환경 변수가 설정되어 있지 않습니다.")
        raise RuntimeError(f"{WEBHOOK_ENV_NAME} 환경 변수가 설정되어 있지 않습니다.")

    reports = build_daily_reports(logger=log, record_recommendations=not dry_run)

    if dry_run:
        log("발송 스킵: DRY_RUN 모드입니다.")
        print("\n===== 메시지 1: 시장/추천/관심종목 =====\n", flush=True)
        print(reports[0], flush=True)
        print("\n===== 메시지 2: 보유종목 관리 =====\n", flush=True)
        print(reports[1], flush=True)
        return 0

    log("Discord 발송 시작")
    send_to_discord(reports, webhook_url)
    log("Discord 전송 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
