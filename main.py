import os
import time
import threading
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yfinance as yf
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from google import genai

# ===================== LOGGING =====================
logging.basicConfig(level=logging.INFO)

# ===================== CONFIG =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise Exception("Missing API keys")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD']

TRADE_HISTORY = []

# ===================== MARKET DATA =====================
def get_data(pair):
    ticker = yf.Ticker(f"{pair}=X")
    data = ticker.history(period="2d", interval="5m")

    if data.empty:
        return None

    df = pd.DataFrame(data)

    df["rsi"] = RSIIndicator(df["Close"], window=14).rsi()
    df["ema_fast"] = EMAIndicator(df["Close"], window=9).ema_indicator()
    df["ema_slow"] = EMAIndicator(df["Close"], window=21).ema_indicator()

    latest = df.iloc[-1]

    return {
        "price": float(latest["Close"]),
        "rsi": float(latest["rsi"]),
        "ema_fast": float(latest["ema_fast"]),
        "ema_slow": float(latest["ema_slow"]),
        "open": float(df.iloc[-1]["Open"]),
        "close": float(df.iloc[-1]["Close"])
    }

# ===================== CANDLE =====================
def candle_signal(o, c):
    if c > o:
        return "BULLISH"
    elif c < o:
        return "BEARISH"
    return "NEUTRAL"

# ===================== FUSION LOGIC =====================
def fusion(data):
    if data["rsi"] is None:
        return None

    candle = candle_signal(data["open"], data["close"])

    if (
        data["rsi"] < 35 and
        data["ema_fast"] > data["ema_slow"] and
        candle == "BULLISH"
    ):
        return "UP"

    if (
        data["rsi"] > 65 and
        data["ema_fast"] < data["ema_slow"] and
        candle == "BEARISH"
    ):
        return "DOWN"

    return None

# ===================== AI CONFIRM =====================
def ai_confirm(pair, price, signal):
    prompt = f"""
Confirm this trade.

Pair: {pair}
Price: {price}
Signal: {signal}

Return:
CONFIRM|reason OR REJECT|reason
"""

    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return res.text.strip()

# ===================== NEWS =====================
def get_news():
    url = "https://news.google.com/rss/search?q=forex+inflation+fed+interest+rate&hl=en-US&gl=US&ceid=US:en"
    r = requests.get(url)
    root = ET.fromstring(r.content)

    news = []
    for item in root.findall(".//item")[:8]:
        news.append(item.find("title").text)

    return news

def analyze_news(news):
    keys = ["fed", "interest", "inflation", "cpi", "nfp", "gdp"]

    results = []

    for n in news:
        impact = "LOW"
        for k in keys:
            if k in n.lower():
                impact = "HIGH"
                break
        results.append((n, impact))

    return results

# ===================== TRADE MONITOR =====================
def monitor(chat_id, pair, direction, entry, duration):
    time.sleep(duration * 60)

    ticker = yf.Ticker(f"{pair}=X")
    data = ticker.history(period="1d", interval="1m")
    exit_price = float(data.iloc[-1]["Close"])

    win = (direction == "UP" and exit_price > entry) or (direction == "DOWN" and exit_price < entry)

    result = "WIN" if win else "LOSS"

    TRADE_HISTORY.append({
        "pair": pair,
        "result": result
    })

    bot.send_message(chat_id, f"""
📊 RESULT

Pair: {pair}
Entry: {entry}
Exit: {exit_price}

Result: {result}
""")

# ===================== ANALYSIS =====================
def run_analysis(chat_id, pair):
    data = get_data(pair)

    if not data:
        bot.send_message(chat_id, "No data")
        return

    signal = fusion(data)

    if not signal:
        bot.send_message(chat_id, "❌ No strong setup (filtered)")
        return

    ai = ai_confirm(pair, data["price"], signal)

    if "REJECT" in ai:
        bot.send_message(chat_id, f"❌ AI rejected\n{ai}")
        return

    bot.send_message(chat_id, f"""
🚀 SIGNAL

Pair: {pair}
Direction: {signal}
RSI: {data['rsi']:.2f}
EMA: {"UP" if data['ema_fast'] > data['ema_slow'] else "DOWN"}

AI: {ai}
""")

    threading.Thread(
        target=monitor,
        args=(chat_id, pair, signal, data["price"], 2),
        daemon=True
    ).start()

# ===================== UI =====================
def menu():
    m = InlineKeyboardMarkup(row_width=2)

    for p in PAIRS:
        m.add(InlineKeyboardButton(f"📊 {p}", callback_data=p))

    m.add(
        InlineKeyboardButton("📊 DASHBOARD", callback_data="DASH"),
        InlineKeyboardButton("📰 NEWS", callback_data="NEWS")
    )

    return m

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "AI Trading Bot", reply_markup=menu())

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    d = c.data

    if d in PAIRS:
        threading.Thread(target=run_analysis, args=(c.message.chat.id, d), daemon=True).start()

    elif d == "DASH":
        wins = sum(1 for t in TRADE_HISTORY if t["result"] == "WIN")
        losses = sum(1 for t in TRADE_HISTORY if t["result"] == "LOSS")

        bot.send_message(c.message.chat.id, f"""
📊 DASHBOARD

Wins: {wins}
Losses: {losses}
Total: {len(TRADE_HISTORY)}
""")

    elif d == "NEWS":
        news = analyze_news(get_news())

        msg = "📰 NEWS\n\n"
        high = 0

        for n, i in news:
            msg += f"{'🔥' if i=='HIGH' else '⚪'} {n}\n"
            if i == "HIGH":
                high += 1

        if high > 0:
            msg += "\n⚠️ HIGH IMPACT NEWS DETECTED"

        bot.send_message(c.message.chat.id, msg)

# ===================== RUN =====================
logging.info("Bot running...")
bot.infinity_polling(skip_pending=True)
