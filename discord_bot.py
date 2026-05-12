from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, timedelta
from typing import Callable

import discord
from discord import app_commands

import bot_commands
import market_group_output
import recommendation_state
import stock_research
import storage
from config import BOT_TOKEN_ENV_NAME, DISCORD_CONTENT_LIMIT, KST


def split_message(content: str, limit: int = DISCORD_CONTENT_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""

    for block in content.split("\n\n"):
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        for line in block.splitlines():
            candidate_line = f"{current}\n{line}".strip() if current else line
            if len(candidate_line) > limit and current:
                chunks.append(current)
                current = line
            else:
                current = candidate_line

    if current:
        chunks.append(current)
    return chunks or ["응답 내용이 없습니다."]


class StockManagerClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.backup_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        if self.backup_task is None or self.backup_task.done():
            self.backup_task = asyncio.create_task(daily_backup_scheduler())
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.clear_commands(guild=guild)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            command_names = ", ".join(command.name for command in synced)
            print(f"[stock-question-bot] slash commands synced to guild {guild_id}: {command_names}", flush=True)
        else:
            synced = await self.tree.sync()
            command_names = ", ".join(command.name for command in synced)
            print(f"[stock-question-bot] global slash commands synced: {command_names}", flush=True)


client = StockManagerClient()


async def daily_backup_scheduler() -> None:
    while True:
        now = datetime.now(KST)
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep(max(60, (next_run - now).total_seconds()))
        try:
            storage.run_daily_backup_if_due(force=True)
            print("[stock-question-bot] daily local backup completed", flush=True)
        except Exception as exc:
            print(f"[stock-question-bot] daily local backup failed: {exc}", flush=True)


def run_health_server() -> None:
    try:
        from flask import Flask

        app = Flask(__name__)

        @app.get("/")
        def health_check() -> tuple[str, int]:
            return "Bot is running", 200

        port = int(os.environ.get("PORT", 10000))
        print(f"Detected Render PORT={port}", flush=True)
        print(f"Flask health server started on port {port}", flush=True)
        app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except Exception as exc:
        print(f"[stock-question-bot] Flask health server failed: {exc}", flush=True)


def start_health_server() -> threading.Thread:
    thread = threading.Thread(target=run_health_server, name="flask-health-server", daemon=True)
    thread.start()
    return thread


async def respond(interaction: discord.Interaction, handler: Callable, *args) -> None:
    await interaction.response.defer(thinking=True)
    try:
        content = await asyncio.to_thread(handler, *args)
    except Exception as exc:
        content = f"명령 처리 중 오류가 발생했습니다.\n오류: **{exc}**"

    chunks = split_message(str(content))
    await interaction.followup.send(chunks[0], allowed_mentions=discord.AllowedMentions.none())
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk, allowed_mentions=discord.AllowedMentions.none())


@client.event
async def on_ready() -> None:
    print("[stock-question-bot] Discord bot connected", flush=True)
    print(f"[stock-question-bot] logged in as {client.user}", flush=True)


@client.tree.command(name="기능", description="주식관리봇 명령어 목록을 보여줍니다.")
async def help_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.help_text)


@client.tree.command(name="종목분석", description="입력한 종목명 또는 티커를 빠르게 분석합니다.")
@app_commands.describe(종목명="종목명 또는 티커")
async def stock_analysis_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, stock_research.stock_detail_report, 종목명)


@client.tree.command(name="종목세부분석", description="기업, 재무, 밸류에이션 중심의 상세 리서치를 보여줍니다.")
@app_commands.describe(종목명="종목명 또는 티커")
async def stock_deep_analysis_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, stock_research.stock_deep_detail_report, 종목명)


@client.tree.command(name="강한테마종목", description="오늘 강한 테마 기준 추천종목 3개 이름만 보여줍니다.")
async def strong_theme_stocks_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.strong_theme_stocks)


@client.tree.command(name="관심추가", description="관심종목을 추가합니다.")
@app_commands.describe(종목명="종목명 또는 티커. 예: 엔비디아, WDC, 두산")
async def add_watchlist_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, bot_commands.add_watchlist, 종목명)


@client.tree.command(name="관심추가직접", description="티커와 테마를 직접 입력해 관심종목을 추가합니다.")
@app_commands.describe(종목명="종목명", 티커="예: 348370.KQ", 테마="예: 2차전지,ESS")
async def add_watchlist_manual_command(interaction: discord.Interaction, 종목명: str, 티커: str, 테마: str) -> None:
    await respond(interaction, bot_commands.add_watchlist_manual, 종목명, 티커, 테마)


@client.tree.command(name="관심삭제", description="관심종목을 삭제합니다.")
@app_commands.describe(종목명="종목명 또는 티커")
async def delete_watchlist_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, bot_commands.delete_watchlist, 종목명)


@client.tree.command(name="관심목록", description="현재 관심종목 목록을 보여줍니다.")
async def list_watchlist_command(interaction: discord.Interaction) -> None:
    await respond(interaction, market_group_output.watchlist_text)


@client.tree.command(name="종목매핑확인", description="종목명 자동검색 결과를 확인합니다.")
@app_commands.describe(종목명="종목명 또는 티커. 예: 풍산, CRCL")
async def mapping_check_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, bot_commands.mapping_check, 종목명)


@client.tree.command(name="관심테마수정", description="관심/보유종목의 테마를 수정합니다.")
@app_commands.describe(종목명="종목명 또는 티커", 테마="예: 원자재,방산")
async def update_item_theme_command(interaction: discord.Interaction, 종목명: str, 테마: str) -> None:
    await respond(interaction, bot_commands.update_item_theme, 종목명, 테마)


@client.tree.command(name="관심매수", description="관심종목을 보유종목으로 이동하거나 자동 매핑으로 추가합니다.")
@app_commands.describe(종목명="종목명. 예: 엔비디아, HK이노엔, WDC", 수량="매수 수량", 매수가="매수 가격")
async def buy_watchlist_command(interaction: discord.Interaction, 종목명: str, 수량: int, 매수가: float) -> None:
    await respond(interaction, bot_commands.buy_watchlist, 종목명, 수량, 매수가)


@client.tree.command(name="보유추가", description="보유종목을 추가하고 관심종목에서는 자동 제외합니다.")
@app_commands.describe(종목명="종목명. 예: 엔비디아, HK이노엔, WDC", 수량="매수 수량", 매수가="매수 가격")
async def add_holding_command(
    interaction: discord.Interaction,
    종목명: str,
    수량: int,
    매수가: float,
) -> None:
    await respond(interaction, bot_commands.add_holding, 종목명, 수량, 매수가)


@client.tree.command(name="분할매도", description="보유 수량 일부를 매도하고 실현손익을 기록합니다.")
@app_commands.describe(종목명="종목명 또는 티커", 수량="매도 수량", 매도가="매도 가격")
async def partial_sell_command(interaction: discord.Interaction, 종목명: str, 수량: int, 매도가: float) -> None:
    await respond(interaction, bot_commands.partial_sell, 종목명, 수량, 매도가)


@client.tree.command(name="전량매도", description="보유 수량 전체를 매도하고 보유목록에서 제거합니다.")
@app_commands.describe(종목명="종목명 또는 티커", 매도가="매도 가격")
async def full_sell_command(interaction: discord.Interaction, 종목명: str, 매도가: float) -> None:
    await respond(interaction, bot_commands.full_sell, 종목명, 매도가)


@client.tree.command(name="보유수정", description="오류 정정용으로 보유 수량과 평단을 강제 수정합니다.")
@app_commands.describe(종목명="종목명 또는 티커", 수량="수정할 수량", 평단="수정할 평단")
async def edit_holding_command(interaction: discord.Interaction, 종목명: str, 수량: int, 평단: float) -> None:
    await respond(interaction, bot_commands.edit_holding, 종목명, 수량, 평단)


@client.tree.command(name="보유삭제", description="보유종목을 삭제합니다.")
@app_commands.describe(종목명="종목명 또는 티커")
async def delete_holding_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, bot_commands.delete_holding, 종목명)


@client.tree.command(name="보유목록", description="현재 보유종목 목록을 보여줍니다.")
async def list_holdings_command(interaction: discord.Interaction) -> None:
    await respond(interaction, market_group_output.holdings_text)


@client.tree.command(name="매매이력", description="최근 매매이력을 보여줍니다.")
@app_commands.describe(종목명="비워두면 전체, 입력하면 해당 종목만 조회")
async def trade_history_command(interaction: discord.Interaction, 종목명: str | None = None) -> None:
    await respond(interaction, bot_commands.trade_history, 종목명)


@client.tree.command(name="성과추적", description="정기 리포트 추천종목의 최근 성과를 보여줍니다.")
async def recommendation_performance_command(interaction: discord.Interaction) -> None:
    await respond(interaction, recommendation_state.recommendation_performance)


@client.tree.command(name="알고리즘성과", description="추천 알고리즘의 전체 성과를 요약합니다.")
async def algorithm_performance_command(interaction: discord.Interaction) -> None:
    await respond(interaction, recommendation_state.algorithm_performance)


@client.tree.command(name="분석성과", description="추천 상태머신 기준 성과를 요약합니다.")
async def analysis_performance_command(interaction: discord.Interaction) -> None:
    await respond(interaction, recommendation_state.analysis_performance)


@client.tree.command(name="포트폴리오점검", description="보유종목 비중, 테마 편중, 리스크를 점검합니다.")
async def portfolio_check_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.portfolio_check)


@client.tree.command(name="조건검색", description="관심/보유/테마 대표종목 안에서 조건 후보를 찾습니다.")
@app_commands.describe(조건="눌림목, 거래량급증, 전고돌파, 추세상승, AI, 전력")
async def condition_search_command(interaction: discord.Interaction, 조건: str) -> None:
    await respond(interaction, bot_commands.condition_search, 조건)


@client.tree.command(name="시장상태", description="현재 시장 상태와 현금 비중 전략을 보여줍니다.")
async def market_status_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.market_status)


@client.tree.command(name="오늘전략", description="오늘 신규매수/관망/현금비중 전략을 보여줍니다.")
async def today_strategy_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.today_strategy)


@client.tree.command(name="강한테마", description="뉴스봇 기반 오늘 강한 테마를 보여줍니다.")
async def strong_themes_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.strong_themes)


@client.tree.command(name="물림", description="손절가, 버팀 구간, 시간손절 기준을 분석합니다.")
@app_commands.describe(종목명="종목명 또는 티커", 평단="평균 단가")
async def stuck_command(interaction: discord.Interaction, 종목명: str, 평단: float) -> None:
    await respond(interaction, bot_commands.stuck, 종목명, 평단)


@client.tree.command(name="테마점검", description="테마의 지속성, 과열도, 리스크를 점검합니다.")
@app_commands.describe(테마명="예: 2차전지")
async def theme_check_command(interaction: discord.Interaction, 테마명: str) -> None:
    await respond(interaction, bot_commands.theme_check, 테마명)


@client.tree.command(name="알림설정", description="목표가/손절가 알림 조건을 저장합니다.")
@app_commands.describe(종목명="종목명", 조건="목표 또는 손절", 가격="알림 가격")
async def set_alert_command(interaction: discord.Interaction, 종목명: str, 조건: str, 가격: float) -> None:
    await respond(interaction, bot_commands.set_alert, 종목명, 조건, 가격)


def main() -> int:
    token = os.getenv(BOT_TOKEN_ENV_NAME)
    if not token:
        raise RuntimeError(f"{BOT_TOKEN_ENV_NAME} 환경 변수가 설정되어 있지 않습니다.")
    storage.run_daily_backup_if_due()
    start_health_server()
    print("[stock-question-bot] Discord bot login started", flush=True)
    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
