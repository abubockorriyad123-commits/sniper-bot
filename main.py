import os
import time
import threading
import requests
import pandas as pd
import telebot

from http.server import BaseHTTPRequestHandler, HTTPServer

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("TWELVE_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")

# =========================
# 12 PAIRS
# =========================

PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY",
    "AUD/USD", "USD/CHF", "NZD/USD",
    "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "AUD/JPY", "CAD/JPY", "GBP/CHF"
]

# =========================
# KEEP ALIVE SERVER
# =========================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot alive")

def run_server():
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()

# =========================
# GET MARKET DATA
# =========================

def get_data(pair):
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=80&apikey={API_KEY}"
    res = requests.get(url).json()

    if "values" not in res:
        return None

    df = pd.DataFrame(res["values"])
    df = df.iloc[::-1]

    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)

    return df

# =========================
# VOLATILITY FILTER
# =========================

def volatility(df):
    return df["high"].iloc[-20:].max() - df["low"].iloc[-20:].min()

def get_active_pairs():
    scores = []

    for p in PAIRS:
        df = get_data(p)
        if df is None:
            continue

        vol = volatility(df)
        scores.append((p, vol))

    scores.sort(key=lambda x: x[1], reverse=True)

    return [x[0] for x in scores[:3]]

# =========================
# NEXT CANDLE PREDICTION
# =========================

def predict_next_candle(df):

    rsi = RSIIndicator(df["close"]).rsi().iloc[-1]

    ema9 = EMAIndicator(df["close"], 9).ema_indicator().iloc[-1]
    ema21 = EMAIndicator(df["close"], 21).ema_indicator().iloc[-1]

    macd = MACD(df["close"])
    macd_val = macd.macd().iloc[-1]
    macd_sig = macd.macd_signal().iloc[-1]

    up = 0
    down = 0

    # RSI
    if rsi < 35:
        up += 2
    elif rsi > 65:
        down += 2

    # EMA
    if ema9 > ema21:
        up += 2
    else:
        down += 2

    # MACD
    if macd_val > macd_sig:
        up += 1
    else:
        down += 1

    total = up + down

    up_prob = (up / total) * 100
    down_prob = (down / total) * 100

    return up_prob, down_prob

# =========================
# ANALYSIS ENGINE
# =========================

def analyze(pair):

    df = get_data(pair)
    if df is None or len(df) < 50:
        return None

    price = df["close"].iloc[-1]

    rsi = RSIIndicator(df["close"]).rsi().iloc[-1]

    ema9 = EMAIndicator(df["close"], 9).ema_indicator().iloc[-1]
    ema21 = EMAIndicator(df["close"], 21).ema_indicator().iloc[-1]

    macd = MACD(df["close"])
    macd_val = macd.macd().iloc[-1]
    macd_sig = macd.macd_signal().iloc[-1]

    trend_up = ema9 > ema21

    score = 0
    direction = None

    # RSI
    if rsi < 35:
        direction = "UP"
        score += 30
    elif rsi > 65:
        direction = "DOWN"
        score += 30

    # MACD
    if direction == "UP" and macd_val > macd_sig:
        score += 25
    elif direction == "DOWN" and macd_val < macd_sig:
        score += 25

    # Trend
    if direction == "UP" and trend_up:
        score += 25
    elif direction == "DOWN" and not trend_up:
        score += 25
    else:
        score += 10

    prob = min(100, score)

    if prob < 80:
        return {
            "signal": "NO SIGNAL",
            "reason": f"Low confidence {prob:.2f}%"
        }

    up_prob, down_prob = predict_next_candle(df)

    return {
        "signal": direction,
        "price": price,
        "score": score,
        "probability": prob,
        "up_prob": up_prob,
        "down_prob": down_prob
    }

# =========================
# AUTO SCAN
# =========================

def auto_scan():

    active = get_active_pairs()

    best = None

    for p in active:

        r = analyze(p)

        if not r or r["signal"] == "NO SIGNAL":
            continue

        if best is None or r["probability"] > best[1]["probability"]:
            best = (p, r)

    return best

# =========================
# COMMAND
# =========================

@bot.message_handler(func=lambda m: m.text.lower() == "needsignal")
def need_signal(msg):

    bot.send_message(msg.chat.id, "🔍 Scanning 12 markets (volatility + candle prediction)...")

    result = auto_scan()

    if not result:
        bot.send_message(msg.chat.id, "🚫 NO HIGH QUALITY SIGNAL (80%+ not found)")
        return

    pair, r = result

    bot.send_message(
        msg.chat.id,
        f"""
🚀 *SNIPER SIGNAL (FINAL)*

Pair: {pair}
Direction: *{r['signal']}*
Price: `{r['price']}`

🎯 Confidence: {r['probability']}%
📊 Score: {r['score']}/100

📈 Next Candle Prediction:
UP: {r['up_prob']:.2f}%
DOWN: {r['down_prob']:.2f}%

⏱ Duration: 1–2 Minutes
"""
    )

# =========================
# START
# =========================

@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id, "🚀 Bot Ready\nType: needsignal")

# =========================
# RUN
# =========================

if __name__ == "__main__":

    threading.Thread(target=run_server).start()
    bot.infinity_polling(skip_pending=True)
