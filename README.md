# 주식관리봇

평일 한국시간 오전 07:50에 GitHub Actions로 실행되어 Discord 주식관리 채널에 데일리 리포트를 발송하는 Python 봇입니다.

## 구성

- `main.py`: 시세 수집, 시장 상태 판단, 점수 계산, 리포트 생성, Discord 발송
- `discord_bot.py`: Discord slash command 질문봇 실행
- `bot_commands.py`: 질문봇 명령어 처리
- `analyzer.py`: 정기 리포트와 질문봇이 공유하는 분석 로직
- `storage.py`: `watchlist.json`, `holdings.json`, `news_summary.json`, `alerts.json`, 매핑 파일 읽기/쓰기
- `config.py`: 공통 설정, 시장 상태별 전략, 테마 키워드
- `theme_config.json`: 우선 분석 대분류 테마와 세부 태그, 대표종목
- `ticker_map.json`: 종목명과 티커 자동 매핑
- `theme_map.json`: 종목명과 테마/세부태그 자동 매핑
- `watchlist.json`: 관심종목
- `holdings.json`: 보유종목
- `alerts.json`: 목표가/손절가 알림 조건
- `news_summary.json`: 뉴스봇 연동 요약 파일
- `.github/workflows/stock-manager.yml`: GitHub Actions 스케줄

## 발송 시간

KST 평일 오전 07:50은 UTC 기준 전날 22:50입니다.

```yaml
cron: "50 22 * * 0-4"
```

GitHub Actions 스케줄은 UTC 일요일~목요일 22:50에 실행되고, Python 코드에서도 KST 주말이면 발송하지 않도록 한 번 더 확인합니다.

## GitHub Secret

Discord 주식관리 채널 Webhook URL을 아래 이름으로 등록하세요.

```text
DISCORD_STOCK_WEBHOOK_URL
```

## 로컬 실행

```bash
pip install -r requirements.txt
python main.py --dry-run
```

`--dry-run`은 Discord 발송 없이 실제 전송될 메시지 1, 메시지 2를 콘솔에 각각 출력합니다.

실제 발송은 아래처럼 실행합니다.

```bash
python main.py
```

## Discord 질문봇

질문봇은 slash command를 받기 위해 계속 실행 중이어야 합니다. GitHub Actions는 예약 실행에는 적합하지만 상시 실행 봇 호스팅에는 적합하지 않습니다. 로컬 PC, 개인 서버, NAS, Railway, Render 같은 상시 실행 환경에서 `discord_bot.py`를 실행하세요.

필수 환경변수:

```text
DISCORD_BOT_TOKEN
```

테스트 서버에 명령어를 빠르게 등록하려면 선택 환경변수 `DISCORD_GUILD_ID`를 설정할 수 있습니다. 설정하지 않으면 global command로 동기화되며 Discord 반영에 시간이 걸릴 수 있습니다.

실행:

```bash
pip install -r requirements.txt
python discord_bot.py
```

### Render 무료 Web Service 배포

Render 무료 플랜에서는 Background Worker 대신 Web Service로 질문봇을 실행할 수 있습니다. `discord_bot.py`는 Discord 봇과 함께 Flask health check 서버를 별도 스레드로 실행해 Render가 열린 포트를 감지할 수 있게 합니다.

Health check:

```text
GET /
Bot is running
```

Render 설정:

```text
Build Command: pip install -r requirements.txt
Start Command: python discord_bot.py
```

저장소에는 `render.yaml`도 포함되어 있어 Render Blueprint로 바로 적용할 수 있습니다. Render에서 New Blueprint를 선택하고 이 저장소를 연결한 뒤, 아래 환경변수만 직접 입력하면 됩니다.

Environment Variables:

```text
DISCORD_BOT_TOKEN=Discord 봇 토큰
DISCORD_GUILD_ID=테스트 서버 ID 선택
PORT=Render가 자동 설정
```

`PORT`가 없으면 로컬 실행용 기본값 `10000`을 사용합니다. 실행 로그에서 `Flask health server started`, `Discord bot login started`, `Discord bot connected`가 보이면 정상입니다.

Slash command를 바로 테스트하려면 `DISCORD_GUILD_ID`를 테스트 서버 ID로 설정하세요. 봇 시작 시 해당 서버의 명령어를 현재 코드 기준으로 즉시 재동기화합니다. 배포 후 아래 두 명령으로 먼저 확인하면 됩니다.

```text
/보유추가 엔비디아 10 120
/보유추가 HK이노엔 50 49500
```

지원 명령어:

- `/기능`: 전체 명령어 목록
- `/종목분석 종목명`: 종목 상세 분석
- `/강한테마종목`: 강한 테마 기준 추천종목 3개 이름만 출력
- `/관심추가 종목명`: 티커와 테마 자동 매핑 후 관심종목 추가. 예: `/관심추가 엔비디아`
- `/관심추가직접 종목명 티커 테마`: 직접 입력해 관심종목 추가. 예: `/관심추가직접 엔켐 348370.KQ 2차전지,ESS`
- `/관심삭제 종목명`: 관심종목 삭제
- `/관심목록`: 관심종목 목록
- `/관심매수 종목명 수량 평단`: 관심종목을 보유종목으로 이동하거나 자동 매핑으로 추가
- `/보유추가 종목명 수량 평단`: 보유종목 추가/업데이트, 관심종목에서는 자동 제외
- `/보유삭제 종목명`: 보유종목 삭제
- `/보유목록`: 보유종목 목록
- `/포트폴리오점검`: 비중, 수익률, 테마 편중, 리스크 점검
- `/시장상태`: 시장 상태와 현금 비중 전략
- `/오늘전략`: 신규매수/관망/현금비중 전략
- `/강한테마`: 뉴스봇 기반 강한 테마
- `/물림 종목명 평단`: 손절가, 버틸 구간, 시간손절 기준
- `/테마점검 테마명`: 테마 지속성, 과열도, 리스크
- `/알림설정 종목명 조건 가격`: 목표가/손절가 알림 조건 저장

## 관심종목

관심종목은 `watchlist.json`에서 관리합니다.

질문봇에서는 종목명만 입력해 관심종목을 추가할 수 있습니다. `/관심추가 엔비디아`처럼 입력하면 `ticker_map.json`에서 티커를 찾고, `theme_map.json`에서 테마와 세부태그를 찾아 `watchlist.json`에 저장합니다. 매핑이 없는 종목은 `/관심추가직접 종목명 티커 테마`로 직접 추가하거나 매핑 파일에 등록하세요.

관심종목은 아직 매수하지 않은 후보군이고, 보유종목은 실제 매수한 포지션입니다. `/보유추가 엔비디아 10 120`처럼 종목명만 입력하면 `ticker_map.json`과 `theme_map.json`에서 티커와 테마를 자동으로 찾아 저장합니다. `/보유추가` 또는 `/관심매수`로 보유종목에 들어간 종목은 `watchlist.json`에서 자동 제외됩니다. `/보유삭제`는 관심종목으로 자동 복귀하지 않으며, 다시 후보로 보고 싶으면 `/관심추가`로 별도 등록합니다.

보유종목 평단은 해당 종목 거래통화 기준입니다. 한국주식은 KRW, 미국주식은 USD로 입력하며 원화/달러 자동 환산은 하지 않습니다.

```json
[
  {
    "name": "종목명",
    "ticker": "000000.KS"
  }
]
```

한국 종목은 코스피 `.KS`, 코스닥 `.KQ` 티커를 사용합니다.

관심종목은 우선 분석 대분류 테마와 세부 태그를 함께 저장할 수 있습니다.

```json
[
  {
    "name": "WDC",
    "ticker": "WDC",
    "themes": ["AI"],
    "subthemes": ["AI인프라", "스토리지"]
  }
]
```

우선 분석 대분류 테마는 `theme_config.json`에서 관리합니다. 현재 우선 테마는 AI, 반도체, 전력, 원전, 2차전지, ESS, 우주항공, 방산, 바이오/제약, 음식료, 로봇, 자율주행, 조선, 원자재, 건설, 금융입니다. 원자재는 세부 태그로 철강, 구리를 허용합니다. 클라우드는 별도 대분류가 아니라 AI의 세부 태그입니다.

`/강한테마종목`과 심층분석 후보군은 전체 시장을 훑지 않고 아래 후보만 사용합니다.

- 보유종목
- 관심종목
- 우선 분석 대분류 테마의 대표종목
- `news_summary.json`에서 감지된 강한 테마 대표종목

심층분석 후보군은 기본 최대 50개로 제한합니다.

## Discord 출력

리포트는 Discord 모바일 가독성을 위해 2개 메시지로 나누어 발송합니다.

- 메시지 1: 시장 상태, 오늘 액션, 강한 테마, 추천 종목 TOP3, 관심종목 점검
- 메시지 2: 보유종목 관리, 수익률, 목표가, 손절가, 액션, 리스크 경고

섹션 제목은 굵게 표시하고, 라벨은 일반 텍스트로 유지하며 값만 굵게 표시합니다.

```text
━━━━━━━━━━
**🏆 추천 종목 TOP3**
━━━━━━━━━━

종목명: **LG에너지솔루션**
퀀트 점수: **80**
매매 타이밍 점수: **40**
액션: **관망**
```

## 뉴스봇 연동

기존 뉴스봇이 핵심 뉴스와 테마만 추려서 `news_summary.json`에 저장하면, 주식관리봇이 이 파일을 읽어 오늘 강한 테마와 종목별 테마 가점에 반영합니다.

예시 형식:

```json
{
  "generated_at": "2026-05-08T07:30:00+09:00",
  "themes": [
    {"name": "2차전지", "score": 5},
    {"name": "바이오/제약", "score": 3}
  ],
  "key_news": [
    {
      "title": "배터리 업종 수급 개선",
      "summary": "2차전지 관련주에 수급이 유입되었습니다.",
      "themes": ["2차전지"]
    }
  ]
}
```

파일이 없거나 비어 있으면 뉴스 연동 없이 기본 관심 테마로 분석합니다.

## 점수 체계

- 퀀트 점수: 이동평균 추세, 20일 모멘텀, 거래량, 변동성, 뉴스 테마 가점
- 매매 타이밍 점수: RSI, 단기 추세, 거래량, 당일 등락률
- 최종 액션: 시장 상태와 두 점수를 함께 반영

## 시장 상태별 전략

- 상승장: 적극 매수 가능
- 변동성 확대장: 확실한 종목만 선별 매매
- 횡보장: 짧은 스윙 중심
- 하락장: 현금 비중 50% 이상 권고

## 실행 로그

GitHub Actions 로그에는 아래 상태가 출력됩니다.

- 리포트 생성 시작
- `watchlist.json` 로드 성공/실패
- `holdings.json` 로드 성공/실패
- 추천/관심 메시지 Discord 발송 성공/실패
- 보유종목 메시지 Discord 발송 성공/실패
- 주말 또는 dry-run 스킵 사유

`workflow_dispatch` 수동 실행은 주말이어도 발송합니다. KST 주말 스킵은 `schedule` 이벤트에서만 적용됩니다.

## 주의

이 봇은 투자 판단 보조용입니다. 실제 매매 결정과 책임은 사용자에게 있습니다.
