import asyncio
import logging
import uuid
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from cipher import decode, encode
from config import BOT_TOKEN, MAX_PIN_ATTEMPTS, PIN_MAX, PIN_MIN, SELF_DESTRUCT_DELAY
from pin_utils import parse_pin_and_text
from storage import (
    arm_self_destruct,
    check_pin,
    clear_pin_buffer,
    get_pin_buffer,
    get_secret,
    init_db,
    pin_attempts,
    pop_self_destruct_target,
    set_pin_buffer,
    store_secret,
)

logging.basicConfig(level=logging.INFO)

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ALERT_TEXT_LIMIT = 190


def secret_keyboard(text: str, pin: str):
    key = store_secret(text, pin)
    return secret_keyboard_for_key(key)


def secret_keyboard_for_key(key: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔓 Расшифровать", callback_data=f"dec:{key}")
    builder.button(
        text=f"💣 Удалить через {SELF_DESTRUCT_DELAY} сек после расшифровки",
        callback_data=f"sd:{key}:{SELF_DESTRUCT_DELAY}",
    )
    builder.adjust(1)
    return builder.as_markup()


def pin_pad_keyboard(key: str, entered: str):
    dots = "•" * len(entered) if entered else "—"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"PIN: {dots}", callback_data=f"pn:{key}")
    for row in ((1, 2, 3), (4, 5, 6), (7, 8, 9)):
        for digit in row:
            builder.button(text=str(digit), callback_data=f"pd:{key}:{digit}")
    builder.button(text="⌫", callback_data=f"pb:{key}")
    builder.button(text="0", callback_data=f"pd:{key}:0")
    builder.button(text="✓", callback_data=f"pc:{key}")
    builder.button(text="✖ Отмена", callback_data=f"px:{key}")
    builder.adjust(1, 3, 3, 3, 3, 1)
    return builder.as_markup()


def pin_format_hint() -> str:
    return (
        f"Укажите PIN в начале ({PIN_MIN}–{PIN_MAX} цифр), затем текст.\n"
        "Пример: 1234 привет"
    )


async def edit_secret_markup(callback: CallbackQuery, reply_markup) -> bool:
    try:
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=reply_markup)
        elif callback.inline_message_id:
            await bot.edit_message_reply_markup(
                inline_message_id=callback.inline_message_id,
                reply_markup=reply_markup,
            )
        else:
            return False
        return True
    except TelegramBadRequest as exc:
        logging.warning("Не удалось обновить клавиатуру: %s", exc)
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


async def schedule_self_destruct(key: str):
    target = pop_self_destruct_target(key)
    if not target:
        return
    asyncio.create_task(
        self_destruct(
            delay=target["delay"],
            chat_id=target.get("chat_id"),
            message_id=target.get("message_id"),
            inline_message_id=target.get("inline_message_id"),
        )
    )


def format_decrypt_alert(plaintext: str) -> str:
    text = plaintext.upper()
    body = f"🔓 {text}"
    if len(body) > ALERT_TEXT_LIMIT:
        return body[: ALERT_TEXT_LIMIT - 1] + "…"
    return body


@dp.message(CommandStart())
async def start_cmd(message: Message):
    me = await bot.get_me()
    await message.answer(
        "🔐 Secret Cipher Bot\n\n"
        "Как отправить:\n"
        f"1. В любом чате: @{me.username} 1234 ваш текст\n"
        "2. Выберите «🔐 Отправить зашифрованным»\n\n"
        "Как прочитать (без перехода в личку):\n"
        "1. Нажмите «🔓 Расшифровать»\n"
        "2. Наберите PIN кнопками под сообщением\n"
        "3. Нажмите ✓ — текст откроется только вам во всплывающем окне\n"
        "   PIN не появится в чате как сообщение\n\n"
        f"«💣 Удалить…» — исчезнет через {SELF_DESTRUCT_DELAY} сек после расшифровки.\n\n"
        f"В личке с ботом: {pin_format_hint()}\n"
        "/decode эмодзи — расшифровать вручную без PIN"
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
        await message.answer("Используйте: /decode эмодзи или ответ на сообщение.")
        return

    decoded = decode(text)
    await message.answer(f"🔓 <code>{decoded}</code>", parse_mode="HTML")


@dp.message(F.text & ~F.text.startswith("/"))
async def auto_encrypt_message(message: Message):
    if message.chat.type != "private":
        return

    pin, text = parse_pin_and_text(message.text or "")
    if not pin:
        await message.answer("🔐 Чтобы зашифровать сообщение:\n\n" + pin_format_hint())
        return

    encrypted = encode(text)
    await message.answer(encrypted, reply_markup=secret_keyboard(text, pin))


@dp.inline_query()
async def inline_handler(inline_query: InlineQuery):
    query = inline_query.query.strip()
    if not query:
        await inline_query.answer(
            results=[],
            cache_time=1,
            is_personal=True,
            switch_pm_text="Как отправить зашифрованное сообщение",
            switch_pm_parameter="start",
        )
        return

    pin, text = parse_pin_and_text(query)
    if not pin:
        await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    id="pin-hint",
                    title=f"⚠️ Сначала PIN ({PIN_MIN}–{PIN_MAX} цифр)",
                    description="Пример: 1234 привет",
                    input_message_content=InputTextMessageContent(
                        message_text="⚠️ Формат: PIN пробел текст. Пример: 1234 привет"
                    ),
                )
            ],
            cache_time=1,
            is_personal=True,
        )
        return

    encrypted = encode(text)
    preview = encrypted if len(encrypted) <= 48 else f"{encrypted[:48]}…"
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="🔐 Отправить зашифрованным",
            description=preview,
            input_message_content=InputTextMessageContent(message_text=encrypted),
            reply_markup=secret_keyboard(text, pin),
        )
    ]

    await inline_query.answer(results=results, cache_time=1, is_personal=True)


@dp.callback_query(F.data.startswith("dec:"))
async def decrypt_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    if not get_secret(key):
        await callback.answer("Сообщение не найдено или срок хранения истёк.", show_alert=True)
        return

    user_id = callback.from_user.id
    set_pin_buffer(user_id, key, "")
    if await edit_secret_markup(callback, pin_pad_keyboard(key, "")):
        await callback.answer("Наберите PIN кнопками. Его не увидят другие.")
    else:
        await callback.answer("Не удалось открыть ввод PIN.", show_alert=True)


@dp.callback_query(F.data.startswith("pn:"))
async def pin_display_callback(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("pd:"))
async def pin_digit_callback(callback: CallbackQuery):
    _, key, digit = callback.data.split(":", 2)
    user_id = callback.from_user.id
    entered = get_pin_buffer(user_id, key)
    if len(entered) >= PIN_MAX:
        await callback.answer("Максимальная длина PIN")
        return
    entered += digit
    set_pin_buffer(user_id, key, entered)
    if await edit_secret_markup(callback, pin_pad_keyboard(key, entered)):
        await callback.answer()
    else:
        await callback.answer("Ошибка обновления клавиатуры", show_alert=True)


@dp.callback_query(F.data.startswith("pb:"))
async def pin_backspace_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    entered = get_pin_buffer(user_id, key)
    set_pin_buffer(user_id, key, entered[:-1])
    if await edit_secret_markup(callback, pin_pad_keyboard(key, entered[:-1])):
        await callback.answer()
    else:
        await callback.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("px:"))
async def pin_cancel_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    clear_pin_buffer(callback.from_user.id, key)
    if await edit_secret_markup(callback, secret_keyboard_for_key(key)):
        await callback.answer("Ввод PIN отменён")
    else:
        await callback.answer("Отменено")


@dp.callback_query(F.data.startswith("pc:"))
async def pin_confirm_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    entered = get_pin_buffer(user_id, key)

    if len(entered) < PIN_MIN:
        await callback.answer(f"PIN должен быть {PIN_MIN}–{PIN_MAX} цифр", show_alert=True)
        return

    if not get_secret(key):
        await callback.answer("Сообщение не найдено или срок хранения истёк.", show_alert=True)
        return

    plaintext = check_pin(key, entered)
    if plaintext is None:
        if pin_attempts(key) >= MAX_PIN_ATTEMPTS:
            clear_pin_buffer(user_id, key)
            await edit_secret_markup(callback, secret_keyboard_for_key(key))
            await callback.answer(
                "Слишком много неверных попыток. Нажмите «Расшифровать» снова.",
                show_alert=True,
            )
            return
        left = MAX_PIN_ATTEMPTS - pin_attempts(key)
        set_pin_buffer(user_id, key, "")
        await edit_secret_markup(callback, pin_pad_keyboard(key, ""))
        await callback.answer(f"Неверный PIN. Осталось попыток: {left}", show_alert=True)
        return

    clear_pin_buffer(user_id, key)
    await edit_secret_markup(callback, secret_keyboard_for_key(key))
    await callback.answer(format_decrypt_alert(plaintext), show_alert=True)
    await schedule_self_destruct(key)


@dp.callback_query(F.data.startswith("sd:"))
async def selfdestruct_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    key = parts[1]
    delay = int(parts[2])

    ok = arm_self_destruct(
        key,
        delay,
        inline_message_id=callback.inline_message_id,
        chat_id=callback.message.chat.id if callback.message else None,
        message_id=callback.message.message_id if callback.message else None,
    )
    if not ok:
        await callback.answer("Сообщение не найдено. Отправьте заново.", show_alert=True)
        return

    await callback.answer(
        f"💣 Удалится через {delay} сек после расшифровки",
        show_alert=True,
    )


async def main():
    init_db()
    me = await bot.get_me()
    logging.info("Запуск бота @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
