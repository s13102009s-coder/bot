import asyncio
import logging
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from cipher import decode, encode
from config import BOT_TOKEN, SELF_DESTRUCT_DELAY
from storage import get_text, store_text

logging.basicConfig(level=logging.INFO)

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def secret_keyboard(text: str):
    key = store_text(text)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔐 Зашифровать", callback_data=f"enc:{key}")
    builder.button(text="🔓 Расшифровать", callback_data=f"dec:{key}")
    builder.button(
        text=f"💣 Удалить через {SELF_DESTRUCT_DELAY} сек",
        callback_data=f"sd:{key}:{SELF_DESTRUCT_DELAY}",
    )
    builder.adjust(1)
    return builder.as_markup()


async def self_destruct(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


@dp.message(Command("start"))
async def start_cmd(message: Message):
    me = await bot.get_me()
    await message.answer(
        "🔐 Secret Cipher Bot\n\n"
        "Функции:\n"
        "• Шифрование текста в эмодзи\n"
        "• Расшифровка эмодзи обратно в текст\n"
        "• Самоуничтожение сообщения\n"
        "• Inline-режим\n\n"
        f"Пример в любом чате:\n"
        f"@{me.username} секретное сообщение\n\n"
        "Команда /decode — расшифровать текст или ответ на сообщение."
    )


@dp.message(Command("decode"))
async def decode_cmd(message: Message):
    text = ""
    if message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            text = parts[1]

    if not text:
        await message.answer("Используйте /decode в ответ на сообщение или: /decode текст")
        return

    decoded = decode(text)
    await message.answer(f"🔓 <code>{decoded}</code>", parse_mode="HTML")


@dp.inline_query()
async def inline_handler(inline_query: InlineQuery):
    query = inline_query.query.strip()
    if not query:
        await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    id="hint",
                    title="Введите текст сообщения",
                    description="Например: привет мир",
                    input_message_content=InputTextMessageContent(
                        message_text="Введите текст после @бота"
                    ),
                )
            ],
            cache_time=1,
            is_personal=True,
        )
        return

    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="Секретное сообщение",
            description=query[:64],
            input_message_content=InputTextMessageContent(message_text=query),
            reply_markup=secret_keyboard(query),
        )
    ]

    await inline_query.answer(results=results, cache_time=1, is_personal=True)


@dp.callback_query(F.data.startswith("enc:"))
async def encrypt_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    text = callback.message.text or get_text(key)
    if not text:
        await callback.answer("Текст не найден. Отправьте сообщение заново.", show_alert=True)
        return

    encrypted = encode(text)
    try:
        await callback.message.edit_text(encrypted)
    except TelegramBadRequest:
        pass

    await callback.answer("🔐 Сообщение зашифровано")


@dp.callback_query(F.data.startswith("dec:"))
async def decrypt_callback(callback: CallbackQuery):
    text = callback.message.text
    if not text:
        await callback.answer("Нечего расшифровывать.", show_alert=True)
        return

    decrypted = decode(text)
    try:
        await callback.message.edit_text(f"🔓 {decrypted}")
    except TelegramBadRequest:
        pass

    await callback.answer("🔓 Сообщение расшифровано")


@dp.callback_query(F.data.startswith("sd:"))
async def selfdestruct_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    key = parts[1]
    delay = int(parts[2])
    text = callback.message.text or get_text(key)
    if not text:
        await callback.answer("Текст не найден.", show_alert=True)
        return

    try:
        await callback.message.edit_text(text)
    except TelegramBadRequest:
        pass

    asyncio.create_task(
        self_destruct(
            callback.message.chat.id,
            callback.message.message_id,
            delay,
        )
    )

    await callback.answer(f"💣 Удаление через {delay} сек")


async def main():
    me = await bot.get_me()
    logging.info("Запуск бота @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
