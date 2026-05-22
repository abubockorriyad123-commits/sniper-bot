import os
import time
import threading
import logging
from datetime import datetime, timedelta

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yfinance as yf
from google import genai

# ===================== LOGGING =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ===================== CONFIG (SECURE) =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise Exception("Missing API keys in environment variables!")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD']


# ===================== MARKET DATA =====================
def get_price(pair):
    try:
        ticker = yf.Ticker(f"{pair}=X")
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            return None
        return float(data.iloc[-1]['Close'])
    except Exception as e:
        logging.error(f"Price fetch error {pair}: {e}")
        return None


# ===================== AI ANALYSIS =====================
def analyze_pair(pair, price):
    prompt = f"""
You are a short-term forex analysis engine.

Pair: {pair}
Price: {price}

Return ONLY in format:
Direction|Duration|Reason

Rules:
- Direction: UP or DOWN
- Duration: 1 or 2 or 3 (minutes only)
- No extra text
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        text = response.text.strip()
        parts = text.split("|")

        if len(parts) < 3:
            return None

        direction = parts[0].strip().upper()
        duration = int(parts[1].strip())
        reason = parts[2].strip()

        if direction not in ["UP", "DOWN"]:
            return None
        if duration not in [1, 2, 3]:
            return None

        return direction, duration, reason

    except Exception as e:
        logging.error(f"AI error: {e}")
        return None


# ===================== RESULT MONITOR =====================
def monitor_trade(chat_id, pair, direction, entry_price, duration):
    time.sleep(duration * 60)

    exit_price = get_price(pair)
    if exit_price is None:
        bot.send_message(chat_id, "⚠️ Exit price fetch failed.")
        return

    win = (
        (direction == "UP" and exit_price > entry_price) or
        (direction == "DOWN" and exit_price < entry_price)
    )

    result = "✅ WIN" if win else "❌ LOSS"

    msg = f"""
📊 TRADE RESULT

Pair: {pair}
Direction: {direction}
Entry: {entry_price}
Exit: {exit_price}

Result: {result}
"""
    bot.send_message(chat_id, msg)


# ===================== MAIN ANALYSIS =====================
def run_analysis(chat_id, pair):
    price = get_price(pair)

    if price is None:
        bot.send_message(chat_id, "⚠️ Market data unavailable.")
        return

    ai_result = analyze_pair(pair, price)

    if not ai_result:
        bot.send_message(chat_id, "⚠️ AI analysis failed.")
        return

    direction, duration, reason = ai_result

    entry_time = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")

    bot.send_message(
        chat_id,
        f"""
🚀 SIGNAL: {pair}

Direction: {direction}
Duration: {duration} min
Entry Time: {entry_time}

Reason: {reason}
"""
    )

    threading.Thread(
        target=monitor_trade,
        args=(chat_id, pair, direction, price, duration),
        daemon=True
    ).start()


# ===================== TELEGRAM UI =====================
@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup(row_width=2)

    buttons = [
        InlineKeyboardButton(f"📊 {p}", callback_data=p)
        for p in PAIRS
    ]

    markup.add(*buttons)

    bot.send_message(
        message.chat.id,
        "⚡ AI Trading Bot Ready\nSelect a pair:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    bot.send_message(call.message.chat.id, f"Analyzing {call.data} ...")
    threading.Thread(
        target=run_analysis,
        args=(call.message.chat.id, call.data),
        daemon=True
    ).start()


# ===================== START BOT =====================
logging.info("Bot is running...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
