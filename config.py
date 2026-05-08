from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")

WEBHOOK_ENV_NAME = "DISCORD_STOCK_WEBHOOK_URL"
BOT_TOKEN_ENV_NAME = "DISCORD_BOT_TOKEN"

WATCHLIST_FILE = "watchlist.json"
HOLDINGS_FILE = "holdings.json"
NEWS_SUMMARY_FILE = "news_summary.json"
ALERTS_FILE = "alerts.json"

HISTORY_PERIOD = "6mo"
HISTORY_INTERVAL = "1d"

MARKET_INDEXES = [
    {"name": "KOSPI", "ticker": "^KS11"},
    {"name": "KOSDAQ", "ticker": "^KQ11"},
]

CASH_RECOMMENDATIONS = {
    "상승장": "20~30%",
    "변동성 확대장": "40~50%",
    "횡보장": "35~45%",
    "하락장": "50% 이상",
}

MARKET_STRATEGIES = {
    "상승장": "적극 매수 가능",
    "변동성 확대장": "확실한 종목만 선별 매매",
    "횡보장": "짧은 스윙 중심",
    "하락장": "현금 비중 50% 이상 권고",
}

DEFAULT_THEMES = [
    "2차전지",
    "음식료/수산",
    "바이오/제약",
]

THEME_KEYWORDS = {
    "2차전지": ["2차전지", "배터리", "전기차", "ESS", "리튬", "양극재", "음극재"],
    "음식료/수산": ["음식료", "식품", "수산", "참치", "해산물", "원양", "가공식품"],
    "바이오/제약": ["바이오", "제약", "신약", "FDA", "임상", "의약품"],
    "반도체": ["반도체", "HBM", "AI칩", "메모리", "파운드리"],
    "AI/로봇": ["AI", "인공지능", "로봇", "자동화"],
    "조선/방산": ["조선", "방산", "방위산업", "수주", "함정"],
    "원전/에너지": ["원전", "원자력", "전력", "에너지", "전력기기"],
    "지주사": ["지주사", "배당", "자사주", "주주환원"],
}

DISCORD_CONTENT_LIMIT = 1900
