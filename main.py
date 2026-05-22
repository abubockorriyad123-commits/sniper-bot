import os
import time
import threading
import requests
import pandas as pd
import telebot

from http.server import BaseHTTPRequestHandler, HTTPServer
from sklearn.linear_model import LogisticRegression

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD

# =========================
# ENV
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("TWELVE_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")

PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY"]

cooldown = {}

# =========================
# KEEP ALIVE SERVER
# =========================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

def run_server():
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()

# =========================
# MARKET DATA
# =========================

def get_data(pair):
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=100&apikey={API_KEY}"
    res = requests.get(url).json()

    if "values" not in res:
        return None

    df = pd.DataFrame(res["values"])
    df = df.iloc[::-1]

    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)

    return df

# =========================
# LIQUIDITY FILTER
# =========================

def liquidity_check(df):
    last = df.iloc[-1]

    body = abs(last["close"] - last["open"])
    wick_up = last["high"] - max(last["close"], last["open"])
    wick_down = min(last["close"], last["open"]) - last["low"]

    if wick_up > body * 2 or wick_down > body * 2:
        return False

    return True

# =========================
# SUPPORT / RESISTANCE
# =========================

def sr_filter(df, price):

    support = df["low"].rolling(20).min().iloc[-1]
    resistance = df["high"].rolling(20).max().iloc[-1]

    near_support = abs(price - support) < price * 0.0015
    near_resistance = abs(price - resistance) < price * 0.0015

    return near_support or near_resistance

# =========================
# SIMPLE AI MODEL
# =========================

model = LogisticRegression()

X_train = [
    [85, 30, 1, 1],
    [60, 70, 0, 0],
    [90, 25, 1, 1],
    [50, 80, 0, 0],
]

y_train = [1, 0, 1, 0]

model.fit(X_train, y_train)

def ai_probability(features):
    return model.predict_proba([features])[0][1] * 100

# =========================
# ANALYSIS ENGINE
# =========================

def analyze(pair):

    df = get_data(pair)
    if df is None or len(df) < 60:
        return None

    price = df["close"].iloc[-1]

    rsi = RSIIndicator(df["close"]).rsi().iloc[-1]

    ema9 = EMAIndicator(df["close"], 9).ema_indicator().iloc[-1]
    ema21 = EMAIndicator(df["close"], 21).ema_indicator().iloc[-1]

    macd = MACD(df["close"])
    macd_val = macd.macd().iloc[-1]
    macd_sig = macd.macd_signal().iloc[-1]

    trend_up = ema9 > ema21

    direction = None
    score = 0

    # RSI logic
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
    if trend_up:
        score += 20
    else:
        score += 10

    # Liquidity + SR
    if liquidity_check(df):
        score += 10

    if sr_filter(df, price):
        score += 10

    # AI features
    features = [score, rsi, int(trend_up), int(macd_val > macd_sig)]
    prob = ai_probability(features)

    # STRICT 90% FILTER
    if prob < 90:
        return {
            "signal": "NO SIGNAL",
            "reason": f"Low confidence {prob:.2f}%"
        }

    return {
        "signal": direction,
        "price": price,
        "rsi": rsi,
        "score": score,
        "probability": prob,
        "trend": "UP" if trend_up else "DOWN"
    }

# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=['start'])
def start(msg):

    text = """
🚀 *SNIPER AI FOREX BOT*

Select a pair:
"""

    for p in PAIRS:
        text += f"\n• {p}"

    bot.send_message(msg.chat.id, text)

# =========================
# HANDLER
# =========================

@bot.message_handler(func=lambda m: True)
def handle(msg):

    pair = msg.text.strip().upper()

    if pair not in PAIRS:
        bot.send_message(msg.chat.id, "❌ Invalid pair")
        return

    now = time.time()

    if pair in cooldown and now - cooldown[pair] < 60:
        bot.send_message(msg.chat.id, "⏳ Cooldown active")
        return

    cooldown[pair] = now

    result = analyze(pair)

    if not result or result["signal"] == "NO SIGNAL":
        bot.send_message(msg.chat.id, f"🚫 NO SIGNAL\n{result['reason']}")
        return

    bot.send_message(
        msg.chat.id,
        f"""
🚀 *SNIPER SIGNAL*

Pair: {pair}
Direction: *{result['signal']}*
Price: `{result['price']}`

🎯 Probability: {result['probability']:.2f}%
📊 Score: {result['score']}/100
📈 Trend: {result['trend']}
"""
    )

# =========================
# MAIN RUN
# =========================

if __name__ == "__main__":

    threading.Thread(target=run_server).start()
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True)).start()

    while True:
        print("💚 Bot alive...")
        time.sleep(60)
