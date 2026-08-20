import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
FEISHU_WEBHOOK = "xxx"

WATCHED_TICKERS = {
    "MSFT": "微软",
    "GOOGL": "谷歌(Alphabet)",
    "AAPL": "苹果",
    "AMZN": "亚马逊",
    "META": "Meta",
    "NVDA": "英伟达",
    "AMD": "AMD",
    "RKLB": "Rocket Lab",
    "INTC": "英特尔",
}


def send_to_feishu(text):
    message = {"msg_type": "text", "content": {"text": text}}
    try:
        response = requests.post(FEISHU_WEBHOOK, json=message, timeout=15)
        result = response.json()
        return result.get("code") == 0
    except Exception as e:
        print(f"发送失败：{e}")
        return False


def fetch_earnings_calendar():
    today = datetime.now().date()
    future = today + timedelta(days=90)
    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": today.strftime("%Y-%m-%d"),
        "to": future.strftime("%Y-%m-%d"),
        "token": FINNHUB_API_KEY,
    }
    try:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        all_earnings = data.get("earningsCalendar", [])
        watched = [e for e in all_earnings if e.get("symbol") in WATCHED_TICKERS]
        return watched
    except Exception as e:
        print(f"查询失败：{e}")
        return []


def check_and_notify():
    today_str = datetime.now().date().strftime("%Y-%m-%d")
    tomorrow_str = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")

    earnings = fetch_earnings_calendar()
    print(f"查询到 {len(earnings)} 条关注公司的财报安排")

    for e in earnings:
        symbol = e.get("symbol")
        date = e.get("date")
        name = WATCHED_TICKERS.get(symbol, symbol)

        if date == today_str:
            text = f"财经Agent 今日财报��醒\n\n{name}({symbol}) 今日发布财报\nQ{e.get('quarter')} {e.get('year')}年"
            send_to_feishu(text)
            print(f"已发送今日提醒：{name}")
        elif date == tomorrow_str:
            text = f"财经Agent 财报预告\n\n{name}({symbol}) 明日发布财报\nQ{e.get('quarter')} {e.get('year')}年"
            send_to_feishu(text)
            print(f"已发送预告提醒：{name}")


if __name__ == "__main__":
    earnings = fetch_earnings_calendar()
    print("=" * 50)
    print("未来90天内，关注公司的财报安排：")
    for e in earnings:
        symbol = e.get("symbol")
        name = WATCHED_TICKERS.get(symbol, symbol)
        print(f"  {e.get('date')}  {name}({symbol})  Q{e.get('quarter')} {e.get('year')}")
    print("=" * 50)

    check_and_notify()
