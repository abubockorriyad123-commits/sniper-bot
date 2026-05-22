import os
import time
import threading
import telebot
from http.server import BaseHTTPRequestHandler, HTTPServer

# =====================
# ENV
# =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# =====================
# KEEP ALIVE SERVER
# =====================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

def run_server():
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()

# =====================
# BOT START
# =====================
def start_bot():
    bot.infinity_polling(skip_pending=True)

# =====================
# MAIN
# =====================
if __name__ == "__main__":

    threading.Thread(target=run_server).start()
    threading.Thread(target=start_bot).start()

    while True:
        print("💚 alive")
        time.sleep(60)
