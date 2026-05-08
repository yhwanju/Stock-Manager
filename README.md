# 주식관리봇

평일 한국시간 오전 07:50에 GitHub Actions로 실행되어 Discord 주식관리 채널에 데일리 리포트를 발송하는 Python 봇입니다.

## 구성

- `main.py`: 시세 수집, 시장 상태 판단, 점수 계산, 리포트 생성, Discord 발송
- `config.py`: 공통 설정, 시장 상태별 전략, 테마 키워드
- `watchlist.json`: 관심종목
- `holdings.json`: 보유종목
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

## 관심종목

관심종목은 `watchlist.json`에서 관리합니다.

```json
[
  {
    "name": "종목명",
    "ticker": "000000.KS"
  }
]
```

한국 종목은 코스피 `.KS`, 코스닥 `.KQ` 티커를 사용합니다.

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
