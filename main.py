import os
import asyncio
import httpx
import base64
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import LabeledPrice, BufferedInputFile
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
BASE_URL = os.getenv("BASE_URL", "https://polza.ai/api/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek/deepseek-v3.2")
ADMIN_ID = os.getenv("ADMIN_ID")

# Клиент для общения с нашим SD Gateway (порт 8000)
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
gateway_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0), base_url=GATEWAY_URL)

SHIRA_PROMPT_PREFIX = "masterpiece, best quality, amazing quality, 4k, very aesthetic, high resolution, ultra-detailed, absurdres, newest, 1girl, solo, silver hair, long hair, small breasts, medium breasts, "
SHIRA_PROMPT_SUFFIX = "BREAK, depth of field, volumetric lighting"

# Негативный промпт из пресета + жесткая защита от "коров"
SHIRA_NEGATIVE_PROMPT = "modern, recent, old, oldest, cartoon, graphic, text, painting, crayon, graphite, abstract, glitch, deformed, mutated, ugly, disfigured, long body, lowres, bad anatomy, bad hands, missing fingers, extra digits, fewer digits, cropped, very displeasing, (worst quality, bad quality:1.2), bad anatomy, sketch, jpeg artifacts, signature, watermark, username, signature, simple background, conjoined, bad ai-generated, huge breasts, large breasts, giant breasts, cow, overly voluptuous, muscular"

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
            "Напиши /packs, чтобы пополнить! ✨",
            parse_mode="HTML"
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
        [types.InlineKeyboardButton(text=f"{TARIFFS['small']['name']} — {TARIFFS['small']['desc']}", callback_data="pack_small")],
        [types.InlineKeyboardButton(text=f"{TARIFFS['medium']['name']} — {TARIFFS['medium']['desc']}", callback_data="pack_medium")],
        [types.InlineKeyboardButton(text=f"{TARIFFS['large']['name']} — {TARIFFS['large']['desc']}", callback_data="pack_large")],
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
    await pre_checkout_query.answer(ok=True)


@dp.message(lambda message: message.successful_payment is not None)
async def process_successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
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
    MAX_LENGTH = 4000
    if len(summary_text) > MAX_LENGTH:
        summary_text = summary_text[:MAX_LENGTH - 3] + "...\n\n⚠️ Память слишком большая, показана только часть."
    await message.answer(text=summary_text)


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    user_text = message.text

    if not user_text:
        return

    user = await get_or_create_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    is_admin = str(user_id) == str(ADMIN_ID)

    if not is_admin:
        credits = await get_message_credits(user_id)
        if credits <= 0:
            await message.answer(
                "Ой, у тебя закончились сообщения... 💭\n\n"
                "Напиши /packs, чтобы пополнить! ✨",
                parse_mode="HTML"
            )
            return

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

        # 🔥 ИСПРАВЛЕНО: распаковываем 3 значения, как в вашей функции extract_image_marker
        clean_text, image_category, image_prompt = extract_image_marker(ai_text)

        await save_message(user_id, "assistant", clean_text)
        await send_safe_message(message, clean_text, parse_mode="Markdown")

        # 🔥 ДОБАВЛЕНО: Списываем 1 кредит за успешный текстовый ответ (если это не админ)
        if not is_admin:
            await use_message_credit(user_id)

        # Запускаем генерацию изображения в фоне (если маркер найден)
        if image_category:
            asyncio.create_task(
                generate_and_send_image_in_background(
                    message=message,
                    user_id=user_id,
                    is_admin=is_admin,
                    image_category=image_category,
                    llm_visual_prompt=image_prompt
                )
            )

        await maybe_summarize(client, user_id, MODEL_NAME)

    except Exception as e:
        print(f"Ошибка при запросе к API: {e}")
        await message.answer(
            "Ой, кажется, я немного задумалась и запуталась... Попробуй ещё раз, я рядом. 💭"
        )


async def send_safe_message(message: types.Message, text: str, parse_mode="Markdown"):
    MAX_LEN = 3800
    if len(text) <= MAX_LEN:
        return await message.answer(text, parse_mode=parse_mode)

    chunks = []
    start = 0
    while start < len(text):
        end = start + MAX_LEN
        if end < len(text) and text[end] not in (' ', '\n', '.'):
            last_space = text.rfind(' ', start, end)
            if last_space != -1:
                end = last_space + 1
        chunks.append(text[start:end])
        start = end

    for i, chunk in enumerate(chunks):
        suffix = f"\n\n*(...продолжение {i + 2}/{len(chunks)})*" if i < len(chunks) - 1 else ""
        await message.answer(chunk + suffix, parse_mode=parse_mode)


async def generate_and_send_image_in_background(message: types.Message, user_id: int, is_admin: bool,
                                                image_category: str, llm_visual_prompt: str):
    """Фоновая задача: рисует Ширу по описанию LLM и отправляет.
    Кредит уже был списан в handle_message за текстовый ответ!"""
    try:
        if llm_visual_prompt:
            final_prompt = f"{SHIRA_PROMPT_PREFIX} {llm_visual_prompt}, {SHIRA_PROMPT_SUFFIX}"
        else:
            final_prompt = f"{SHIRA_PROMPT_PREFIX} {image_category}, sitting at desk, soft lighting, looking at viewer, {SHIRA_PROMPT_SUFFIX}"

        payload = {
            "prompt": final_prompt,
            "negative_prompt": SHIRA_NEGATIVE_PROMPT,
            "steps": 20,
            "width": 832,
            "height": 1216,
            "cfg_scale": 4.5,
            "sampler_name": "Euler a",
            "scheduler": "Karras",
            "clip_skip": 2
        }

        resp = await gateway_client.post("/sdapi/v1/txt2img", json=payload)
        resp.raise_for_status()
        task_id = resp.json().get("task_id")

        if not task_id:
            raise ValueError("Gateway не вернул task_id")

        for _ in range(100):
            await asyncio.sleep(3.0)

            status_resp = await gateway_client.get(f"/sdapi/v1/task/{task_id}")
            if status_resp.status_code != 200:
                continue

            res = status_resp.json()
            status = res.get("status")

            if status == "completed":
                # УСПЕХ! Кредиты уже списаны в handle_message, здесь ничего не трогаем.

                image_b64 = res.get("image") or (res.get("images", [None])[0] if res.get("images") else None)
                if image_b64:
                    image_bytes = base64.b64decode(image_b64)
                    photo = BufferedInputFile(file=image_bytes, filename="shira_art.jpg")

                    captions = {
                        "cute": "✨ Вот, я постаралась и нарисовала для тебя...",
                        "support": "🫂 Я всегда рядом. Держись.",
                        "thinking": "🤔 Хм, интересная мысль...",
                        "congratulations": "🎉 Я горжусь тобой!"
                    }
                    caption = captions.get(image_category, "✨ Вот что у меня получилось!")
                    await message.answer_photo(photo=photo, caption=caption)
                return

            elif status == "failed":
                await message.answer(
                    "😿 Увы, мои кисти запутались, и у меня не получилось это нарисовать... Попробуй описать иначе!")
                return

        await message.answer("😿 Я рисовала слишком долго и устала... Попробуй попросить ещё раз позже!")

    except Exception as e:
        print(f"Ошибка фоновой генерации для user_{user_id}: {e}")


async def main():
    await init_db()
    print("Бот Шира-тян запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())