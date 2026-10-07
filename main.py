import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import LabeledPrice
from openai import AsyncOpenAI
from dotenv import load_dotenv

from database import (
    init_db, get_or_create_user, save_message, get_recent_messages,
    get_message_credits, use_message_credit, add_message_credits, save_payment
)
from prompts import SYSTEM_PROMPT
from memory import maybe_summarize
from images import extract_image_marker, send_image_from_category

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL", "https://api.deepseek.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
ADMIN_ID = os.getenv("ADMIN_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

MAX_SHORT_TERM_MESSAGES = 12

TARIFFS = {
    "small": {"msgs": 100, "stars": 60, "name": "🔮 100 сообщений", "desc": "60 ⭐"},
    "medium": {"msgs": 300, "stars": 160, "name": "🚀 300 сообщений", "desc": "160 ⭐"},
    "large": {"msgs": 1000, "stars": 490, "name": "👑 1000 сообщений", "desc": "490 ⭐"},
}


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = await get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    name = user["first_name"] or user["username"] or "друг"

    welcome_text = (
        f"Привет, {name}! Я Шира. Рада, что ты снова заглянул. 💫\n\n"
        "Я тут, чтобы быть рядом: помочь с кодом, разобрать сложную тему, "
        "или просто поболтать, если день выдался тяжёлым.\n\n"
        "Напиши /help, чтобы увидеть все команды.\n\n"
        "Расскажи, как ты? Над чем сейчас работаешь?"
    )
    await message.answer(welcome_text)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "📋 <b>Команды Ширы-тян:</b>\n\n"
        "/start — Начать диалог\n"
        "/help — Эта справка\n"
        "/balance — Проверить баланс сообщений\n"
        "/packs — Купить пакет сообщений\n"
        "/clear — Очистить недавнюю переписку\n"
        "/forget — Полный сброс памяти\n"
        "/memory — Что я помню о тебе\n\n"
        "💡 Просто пиши мне, я отвечу!"
    )
    await message.answer(help_text, parse_mode="HTML")


@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    # Сначала убеждаемся, что пользователь существует
    await get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )
    credits = await get_message_credits(message.from_user.id)

    if credits > 0:
        await message.answer(
            f"💎 У тебя осталось <b>{credits}</b> сообщений.\n\n"
            "Напиши /packs, чтобы пополнить ✨",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "Ой, у тебя закончились сообщения... 💭\n\n"
            "Напиши /packs, чтобы пополнить! ✨"
        )


@dp.message(Command("packs"))
async def cmd_packs(message: types.Message):
    await get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )
    credits = await get_message_credits(message.from_user.id)

    packs_text = (
        f"💎 <b>Пакеты сообщений</b>\n\n"
        f"Твой баланс: <b>{credits}</b> сообщений\n\n"
        "Выбери пакет 👇"
    )

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text=f"{TARIFFS['small']['name']} — {TARIFFS['small']['desc']}",
            callback_data="pack_small"
        )],
        [types.InlineKeyboardButton(
            text=f"{TARIFFS['medium']['name']} — {TARIFFS['medium']['desc']}",
            callback_data="pack_medium"
        )],
        [types.InlineKeyboardButton(
            text=f"{TARIFFS['large']['name']} — {TARIFFS['large']['desc']}",
            callback_data="pack_large"
        )],
    ])

    await message.answer(packs_text, parse_mode="HTML", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("pack_"))
async def process_pack_selection(callback_query: types.CallbackQuery):
    pack_id = callback_query.data.replace("pack_", "")
    pack = TARIFFS.get(pack_id)

    if not pack:
        await callback_query.answer("Пакет не найден", show_alert=True)
        return

    prices = [LabeledPrice(label=pack["name"], amount=pack["stars"])]

    await bot.send_invoice(
        chat_id=callback_query.message.chat.id,
        title=pack["name"],
        description=f"Пакет из {pack['msgs']} сообщений для общения с Широй-тян",
        payload=f"pack_{pack_id}",
        provider_token="",
        currency="XTR",
        prices=prices,
    )

    await callback_query.answer()


@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    # ИСПРАВЛЕНО: используем pre_checkout_query.answer(), а не bot.answer_pre_checkout_query()
    await pre_checkout_query.answer(ok=True)


@dp.message(lambda message: message.successful_payment is not None)
async def process_successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload

    # Парсим payload: "pack_small" -> "small"
    pack_id = payload.replace("pack_", "")
    pack = TARIFFS.get(pack_id)

    if pack:
        await save_payment(
            user_id=message.from_user.id,
            amount=payment.total_amount,
            telegram_charge_id=payment.telegram_payment_charge_id or "",
            provider_charge_id=payment.provider_payment_charge_id or ""
        )
        await add_message_credits(message.from_user.id, pack["msgs"])

        new_balance = await get_message_credits(message.from_user.id)

        await message.answer(
            f"✨ <b>Спасибо!</b>\n\n"
            f"Добавлено <b>{pack['msgs']}</b> сообщений!\n"
            f"Твой баланс: <b>{new_balance}</b> 💎",
            parse_mode="HTML"
        )
    else:
        await message.answer("Ой, что-то пошло не так... Напиши /packs и попробуй ещё раз 💭")


@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    from database import clear_old_messages
    await clear_old_messages(message.from_user.id, keep_last=0)
    await message.answer("Окей, я забыла нашу недавнюю переписку. Но главное я помню — не волнуйся. 😊")


@dp.message(Command("forget"))
async def cmd_forget(message: types.Message):
    from database import clear_old_messages, update_long_term_memory
    await clear_old_messages(message.from_user.id, keep_last=0)
    await update_long_term_memory(message.from_user.id, "")
    await message.answer("Хорошо, я всё забыла. Как будто мы встретились впервые. Привет! 👋")


@dp.message(Command("memory"))
async def cmd_memory(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    summary_text = user.get("long_term_memory") or "Память пуста "

    # === ЗАЩИТА ОТ ДЛИННОГО СООБЩЕНИЯ ===
    MAX_LENGTH = 4000
    if len(summary_text) > MAX_LENGTH:
        summary_text = summary_text[:MAX_LENGTH - 3] + "...\n\n⚠️ Память слишком большая, показана только часть."
    # ====================================

    await message.answer(text=summary_text)


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    user_text = message.text

    if not user_text:
        return

    # СНАЧАЛА создаём/получаем пользователя (чтобы кредиты были начислены)
    user = await get_or_create_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    # ПРОВЕРКА НА АДМИНА: если это ты, пропускаем проверку кредитов
    is_admin = str(user_id) == str(ADMIN_ID)

    if not is_admin:
        # Для обычных пользователей проверяем и списываем кредит
        if not await use_message_credit(user_id):
            credits = await get_message_credits(user_id)
            await message.answer(
                f"Ой, у тебя закончились сообщения... 💭\n\n"
                f"Баланс: <b>{credits}</b>\n\n"
                "Напиши /packs, чтобы пополнить! ✨",
                parse_mode="HTML"
            )
            return

    # Дальше всё как обычно: сохраняем сообщение, отправляем в API и т.д.
    await save_message(user_id, "user", user_text)

    messages_for_api = [{"role": "system", "content": SYSTEM_PROMPT}]

    if user["long_term_memory"]:
        messages_for_api.append({
            "role": "system",
            "content": f"[ДОЛГОСРОЧНАЯ ПАМЯТЬ О СОБЕСЕДНИКЕ]:\n{user['long_term_memory']}"
        })

    recent = await get_recent_messages(user_id, limit=MAX_SHORT_TERM_MESSAGES)
    for role, content in recent:
        messages_for_api.append({"role": role, "content": content})

    try:
        await bot.send_chat_action(chat_id=user_id, action="typing")

        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages_for_api,
            temperature=0.75,
            top_p=0.9
        )

        ai_text = response.choices[0].message.content
        clean_text, image_category, image_caption = extract_image_marker(ai_text)

        await save_message(user_id, "assistant", clean_text)
        await send_safe_message(message, clean_text, parse_mode="Markdown")

        if image_category:
            await send_image_from_category(message, image_category, image_caption)

        await maybe_summarize(client, user_id, MODEL_NAME)

    except Exception as e:
        print(f"Ошибка при запросе к API: {e}")
        await message.answer(
            "Ой, кажется, я немного задумалась и запуталась... Попробуй ещё раз, я рядом. 💭"
        )


async def send_safe_message(message: types.Message, text: str, parse_mode="Markdown"):
    """Отправляет сообщение, разбивая на части, если оно > 3800 символов."""
    MAX_LEN = 3800

    if len(text) <= MAX_LEN:
        return await message.answer(text, parse_mode=parse_mode)

    chunks = []
    start = 0
    while start < len(text):
        end = start + MAX_LEN
        # Если мы внутри слова, откатываемся до последнего пробела
        if end < len(text) and text[end] not in (' ', '\n', '.'):
            last_space = text.rfind(' ', start, end)
            if last_space != -1:
                end = last_space + 1
        chunks.append(text[start:end])
        start = end

    for i, chunk in enumerate(chunks):
        suffix = f"\n\n*(...продолжение {i + 2}/{len(chunks)})*" if i < len(chunks) - 1 else ""
        await message.answer(chunk + suffix, parse_mode=parse_mode)


async def main():
    await init_db()
    print("Бот Шира-тян запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())