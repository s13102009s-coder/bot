import asyncio
import logging
import uuid
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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
    get_secret,
    init_db,
    pin_attempts,
    pop_self_destruct_target,
    set_pending_decrypt,
    get_pending_decrypt,
    store_secret,
)

logging.basicConfig(level=logging.INFO)

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class DecryptFlow(StatesGroup):
    waiting_pin = State()


def secret_keyboard(text: str, pin: str):
    key = store_secret(text, pin)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔓 Расшифровать", callback_data=f"dec:{key}")
    builder.button(
        text=f"💣 Удалить через {SELF_DESTRUCT_DELAY} сек после расшифровки",
        callback_data=f"sd:{key}:{SELF_DESTRUCT_DELAY}",
    )
    builder.adjust(1)
    return builder.as_markup()


def pin_format_hint() -> str:
    return (
        f"Укажите PIN в начале ( {PIN_MIN}–{PIN_MAX} цифр ), затем текст.\n"
        "Пример: 1234 привет"
    )


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


async def begin_pin_decrypt(user_id: int, key: str, state: FSMContext) -> bool:
    if not get_secret(key):
        return False
    await state.set_state(DecryptFlow.waiting_pin)
    await state.update_data(decrypt_key=key)
    set_pending_decrypt(user_id, key)
    await bot.send_message(
        user_id,
        "🔓 Введите PIN для расшифровки.\n"
        "Текст будет показан только вам в этом чате.\n"
        "В группе сообщение останется зашифрованным.",
    )
    return True


@dp.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject, state: FSMContext):
    me = await bot.get_me()
    args = (command.args or "").strip()

    if args.startswith("dec_"):
        key = args[4:]
        if await begin_pin_decrypt(message.from_user.id, key, state):
            return
        await message.answer("Сообщение не найдено или срок хранения истёк.")
        return

    await message.answer(
        "🔐 Secret Cipher Bot\n\n"
        "Как отправить зашифрованное сообщение:\n"
        f"1. В любом чате: @{me.username} 1234 ваш текст\n"
        f"   (PIN — {PIN_MIN}–{PIN_MAX} цифр, затем пробел, затем текст)\n"
        "2. Выберите «🔐 Отправить зашифрованным»\n"
        "3. В чат уходят эмодзи\n\n"
        "Как прочитать:\n"
        "1. Нажмите «🔓 Расшифровать»\n"
        "2. Бот попросит PIN в личке\n"
        "3. После верного PIN текст придёт только вам\n\n"
        f"Опционально: «💣 Удалить…» — исчезнет через {SELF_DESTRUCT_DELAY} сек "
        "после успешной расшифровки.\n\n"
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


async def process_pin_entry(message: Message, state: FSMContext, key: str) -> bool:
    """Проверяет PIN и отправляет расшифрованный текст. True — обработано."""
    if not key or not get_secret(key):
        await state.clear()
        await message.answer("Сообщение не найдено или срок хранения истёк.")
        return True

    pin = (message.text or "").strip()
    if not pin.isdigit():
        await message.answer("PIN должен состоять только из цифр.")
        return True

    plaintext = check_pin(key, pin)
    if plaintext is None:
        if pin_attempts(key) >= MAX_PIN_ATTEMPTS:
            await state.clear()
            await message.answer(
                "Слишком много неверных попыток. Нажмите «Расшифровать» в сообщении снова."
            )
            return True
        left = MAX_PIN_ATTEMPTS - pin_attempts(key)
        await message.answer(f"Неверный PIN. Осталось попыток: {left}")
        return True

    await state.clear()
    set_pending_decrypt(message.from_user.id, None)
    await message.answer(
        f"🔓 Сообщение:\n\n<code>{plaintext.upper()}</code>",
        parse_mode="HTML",
    )
    await schedule_self_destruct(key)
    return True


@dp.message(DecryptFlow.waiting_pin, F.text)
async def receive_pin(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("decrypt_key")
    await process_pin_entry(message, state, key)


@dp.message(
    F.chat.type == "private",
    F.text.regexp(rf"^\d{{{PIN_MIN},{PIN_MAX}}}$"),
    ~StateFilter(DecryptFlow.waiting_pin),
)
async def receive_pin_fallback(message: Message, state: FSMContext):
    key = get_pending_decrypt(message.from_user.id)
    if not key:
        return
    await state.set_state(DecryptFlow.waiting_pin)
    await state.update_data(decrypt_key=key)
    await process_pin_entry(message, state, key)


@dp.message(
    F.text & ~F.text.startswith("/"),
    ~StateFilter(DecryptFlow.waiting_pin),
)
async def auto_encrypt_message(message: Message):
    if message.chat.type != "private":
        return

    pin, text = parse_pin_and_text(message.text or "")
    if not pin:
        await message.answer(
            "🔐 Чтобы зашифровать сообщение:\n\n" + pin_format_hint()
        )
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
                        message_text=f"⚠️ Формат: PIN пробел текст. Пример: 1234 привет"
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
async def decrypt_callback(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    if not get_secret(key):
        await callback.answer("Сообщение не найдено или срок хранения истёк.", show_alert=True)
        return

    me = await bot.get_me()
    user_id = callback.from_user.id

    try:
        ok = await begin_pin_decrypt(user_id, key, state)
        if ok:
            await callback.answer("Введите PIN в личке с ботом")
        else:
            await callback.answer("Сообщение не найдено.", show_alert=True)
    except TelegramForbiddenError:
        await callback.answer(
            "Сначала откройте бота и нажмите Start",
            show_alert=True,
            url=f"https://t.me/{me.username}?start=dec_{key}",
        )


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
