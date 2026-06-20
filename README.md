# Secret Cipher Bot

Telegram-бот: шифрование кириллицы в эмодзи, inline-режим, самоуничтожение сообщений.

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env   # вставьте BOT_TOKEN от @BotFather
python bot.py
```

В @BotFather включите inline: `/setinline`

## Файлы проекта (что загружать на GitHub)

```
secret-cipher-bot/
├── bot.py              ← код бота
├── cipher.py           ← шифрование эмодзи
├── config.py           ← настройки
├── storage.py          ← хранение для кнопок
├── requirements.txt    ← зависимости Python
├── .env.example        ← шаблон (скопировать в .env)
├── .gitignore
├── README.md           ← этот файл
├── ИНСТРУКЦИЯ.md       ← полная пошаговая инструкция
├── ПОЯСНЕНИЕ_ПРОЕКТА.md ← описание проекта для курсовой
├── Procfile            ← для Railway
├── Dockerfile          ← для Docker
└── cipherbot.service   ← автозапуск на VPS (systemd)
```

**Не загружать на GitHub:** `.env`, `venv/`, `__pycache__/`, `.DS_Store`

## Лицензия

MIT
