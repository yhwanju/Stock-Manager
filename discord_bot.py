from __future__ import annotations

import asyncio
import os
import threading
from typing import Callable

import discord
from discord import app_commands

import bot_commands
from config import BOT_TOKEN_ENV_NAME, DISCORD_CONTENT_LIMIT


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

    async def setup_hook(self) -> None:
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


def run_health_server() -> None:
    try:
        from flask import Flask

        app = Flask(__name__)

        @app.get("/")
        def health_check() -> tuple[str, int]:
            return "Bot is running", 200

        port = int(os.environ.get("PORT", 10000))
        print(f"Flask health server started on port {port}", flush=True)
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
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


@client.tree.command(name="종목분석", description="입력한 종목명 또는 티커를 상세 분석합니다.")
@app_commands.describe(종목명="종목명 또는 티커")
async def stock_analysis_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, bot_commands.stock_analysis, 종목명)


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
    await respond(interaction, bot_commands.list_watchlist)


@client.tree.command(name="관심매수", description="관심종목을 보유종목으로 이동하거나 자동 매핑으로 추가합니다.")
@app_commands.describe(종목명="종목명. 예: 엔비디아, HK이노엔, WDC", 수량="매수 수량", 평단="평균 단가")
async def buy_watchlist_command(interaction: discord.Interaction, 종목명: str, 수량: int, 평단: float) -> None:
    await respond(interaction, bot_commands.buy_watchlist, 종목명, 수량, 평단)


@client.tree.command(name="보유추가", description="보유종목을 추가하고 관심종목에서는 자동 제외합니다.")
@app_commands.describe(종목명="종목명. 예: 엔비디아, HK이노엔, WDC", 수량="보유 수량", 평단="평균 단가")
async def add_holding_command(
    interaction: discord.Interaction,
    종목명: str,
    수량: int,
    평단: float,
) -> None:
    await respond(interaction, bot_commands.add_holding, 종목명, 수량, 평단)


@client.tree.command(name="보유삭제", description="보유종목을 삭제합니다.")
@app_commands.describe(종목명="종목명 또는 티커")
async def delete_holding_command(interaction: discord.Interaction, 종목명: str) -> None:
    await respond(interaction, bot_commands.delete_holding, 종목명)


@client.tree.command(name="보유목록", description="현재 보유종목 목록을 보여줍니다.")
async def list_holdings_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.list_holdings)


@client.tree.command(name="포트폴리오점검", description="보유종목 비중, 테마 편중, 리스크를 점검합니다.")
async def portfolio_check_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.portfolio_check)


@client.tree.command(name="시장상태", description="현재 시장 상태와 현금 비중 전략을 보여줍니다.")
async def market_status_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.market_status)


@client.tree.command(name="오늘전략", description="오늘 신규매수/관망/현금비중 전략을 보여줍니다.")
async def today_strategy_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.today_strategy)


@client.tree.command(name="강한테마", description="뉴스봇 기반 오늘 강한 테마를 보여줍니다.")
async def strong_themes_command(interaction: discord.Interaction) -> None:
    await respond(interaction, bot_commands.strong_themes)


@client.tree.command(name="물림", description="손절가, 버틸 구간, 시간손절 기준을 분석합니다.")
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
    start_health_server()
    print("[stock-question-bot] Discord bot login started", flush=True)
    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
