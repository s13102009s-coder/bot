import os
import sys

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("Ошибка: задайте переменную BOT_TOKEN в .env или окружении", file=sys.stderr)
    sys.exit(1)

TTL_SECONDS = 3600
SELF_DESTRUCT_DELAY = 10
PIN_MIN = 4
PIN_MAX = 8
MAX_PIN_ATTEMPTS = 3
DB_PATH = os.getenv("DB_PATH", "cipher_bot.db")
