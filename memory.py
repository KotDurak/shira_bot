import asyncio
from typing import List, Tuple
from openai import AsyncOpenAI
from database import (
    get_message_count, get_all_messages_for_summary,
    get_or_create_user, update_long_term_memory, clear_old_messages
)
from prompts import SUMMARIZATION_PROMPT

# Порог: когда суммаризировать (количество сообщений в краткосрочной памяти)
SUMMARIZE_THRESHOLD = 20
# Сколько сообщений оставить после суммаризации
KEEP_AFTER_SUMMARY = 6


async def summarize_conversation(client: AsyncOpenAI, user_id: int, model_name: str):
    """Фоновая суммаризация диалога в долгосрочную память"""
    try:
        user = await get_or_create_user(user_id)
        current_memory = user["long_term_memory"]

        messages = await get_all_messages_for_summary(user_id)
        if not messages:
            return

        # Формируем текст новых сообщений
        new_messages_text = "\n".join([f"{role}: {content}" for role, content in messages])

        prompt = SUMMARIZATION_PROMPT.format(
            current_memory=current_memory or "(пусто, это первый разговор)",
            new_messages=new_messages_text
        )

        response = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,  # Низкая температура для фактологичности
        )

        new_memory = response.choices[0].message.content.strip()

        # Сохраняем обновлённую память
        await update_long_term_memory(user_id, new_memory)

        # Чистим старые сообщения, оставляя только последние
        await clear_old_messages(user_id, keep_last=KEEP_AFTER_SUMMARY)

        print(f"[Memory] Суммаризация для пользователя {user_id} завершена")

    except Exception as e:
        print(f"[Memory] Ошибка суммаризации для {user_id}: {e}")


async def maybe_summarize(client: AsyncOpenAI, user_id: int, model_name: str):
    """Проверяет, нужна ли суммаризация, и запускает её в фоне"""
    count = await get_message_count(user_id)
    if count >= SUMMARIZE_THRESHOLD:
        # Запускаем в фоне, чтобы не блокировать ответ пользователю
        asyncio.create_task(summarize_conversation(client, user_id, model_name))