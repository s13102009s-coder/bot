import asyncio
import logging
import uuid
from typing import Optional

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
from storage import arm_self_destruct, get_text, pop_self_destruct_delay, store_text

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


async def edit_secret_message(
    callback: CallbackQuery,
    text: str,
    reply_markup=None,
) -> bool:
    """Редактирование обычного и inline-сообщения (через inline_message_id)."""
    try:
        if callback.message:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        elif callback.inline_message_id:
            await bot.edit_message_text(
                text=text,
                inline_message_id=callback.inline_message_id,
                reply_markup=reply_markup,
            )
        else:
            return False
        return True
    except TelegramBadRequest as exc:
        logging.warning("Не удалось изменить сообщение: %s", exc)
        return False


async def self_destruct(
    *,
    delay: int,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
    inline_message_id: Optional[str] = None,
):
    await asyncio.sleep(delay)
    try:
        if chat_id is not None and message_id is not None:
            await bot.delete_message(chat_id, message_id)
        elif inline_message_id:
            await bot.edit_message_text(
                text="💣 Сообщение удалено",
                inline_message_id=inline_message_id,
            )
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
        "• Самоуничтожение после расшифровки\n"
        "• Inline-режим (сразу в эмодзи)\n\n"
        f"Пример в любом чате:\n"
        f"@{me.username} секретное сообщение\n\n"
        "/encrypt текст — зашифровать\n"
        "/decode — расшифровать ответ или текст после команды."
    )


@dp.message(Command("encrypt", "encode"))
async def encrypt_cmd(message: Message):
    text = ""
    if message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            text = parts[1]

    if not text:
        await message.answer("Используйте /encrypt текст или ответ на сообщение.")
        return

    encrypted = encode(text)
    await message.answer(encrypted)


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

    encrypted = encode(query)
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="Секретное сообщение",
            description=encrypted[:64],
            input_message_content=InputTextMessageContent(message_text=encrypted),
            reply_markup=secret_keyboard(query),
        )
    ]

    await inline_query.answer(results=results, cache_time=1, is_personal=True)


def message_text_from_callback(callback: CallbackQuery) -> Optional[str]:
    if callback.message and callback.message.text:
        return callback.message.text.removeprefix("🔓 ").strip()
    return None


@dp.callback_query(F.data.startswith("enc:"))
async def encrypt_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    text = message_text_from_callback(callback) or get_text(key)
    if not text:
        await callback.answer("Текст не найден. Отправьте сообщение заново.", show_alert=True)
        return

    encrypted = encode(text)
    if not await edit_secret_message(callback, encrypted):
        await callback.answer("Не удалось зашифровать сообщение.", show_alert=True)
        return

    await callback.answer("🔐 Сообщение зашифровано")


@dp.callback_query(F.data.startswith("dec:"))
async def decrypt_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    current_text = message_text_from_callback(callback)

    if current_text:
        decrypted = decode(current_text)
    else:
        stored = get_text(key)
        if not stored:
            await callback.answer(
                "Текст не найден. Отправьте сообщение заново.",
                show_alert=True,
            )
            return
        decrypted = stored.upper()

    if not decrypted:
        await callback.answer("Нечего расшифровывать.", show_alert=True)
        return

    if not await edit_secret_message(callback, f"🔓 {decrypted}"):
        await callback.answer("Не удалось расшифровать сообщение.", show_alert=True)
        return

    delay = pop_self_destruct_delay(key)
    if delay:
        if callback.message:
            asyncio.create_task(
                self_destruct(
                    delay=delay,
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                )
            )
        elif callback.inline_message_id:
            asyncio.create_task(
                self_destruct(
                    delay=delay,
                    inline_message_id=callback.inline_message_id,
                )
            )
        await callback.answer(
            f"🔓 Расшифровано. Удаление через {delay} сек.",
            show_alert=False,
        )
        return

    await callback.answer("🔓 Сообщение расшифровано")


@dp.callback_query(F.data.startswith("sd:"))
async def selfdestruct_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    key = parts[1]
    delay = int(parts[2])

    if not arm_self_destruct(key, delay):
        await callback.answer("Текст не найден. Отправьте сообщение заново.", show_alert=True)
        return

    await callback.answer(
        f"💣 Удалится через {delay} сек после расшифровки",
        show_alert=True,
    )


async def main():
    me = await bot.get_me()
    logging.info("Запуск бота @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
