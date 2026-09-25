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
    try:
        user = await get_or_create_user(user_id)
        current_memory = user["long_term_memory"]

        messages = await get_all_messages_for_summary(user_id)
        if not messages:
            return

        new_messages_text = "\n".join([f"{role}: {content}" for role, content in messages])

        prompt = SUMMARIZATION_PROMPT.format(
            current_memory=current_memory or "(пусто, это первый разговор)",
            new_messages=new_messages_text
        )

        response = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000,  # === ДОБАВИТЬ: жёсткий лимит на вывод (~700-800 слов) ===
        )

        new_memory = response.choices[0].message.content.strip()

        # === ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: если память всё равно слишком длинная ===
        MAX_MEMORY_LENGTH = 2000  # символов
        if len(new_memory) > MAX_MEMORY_LENGTH:
            # Можно либо обрезать, либо отправить повторный запрос с более жёстким промптом
            new_memory = new_memory[:MAX_MEMORY_LENGTH - 3] + "..."
        # ====================================================================

        await update_long_term_memory(user_id, new_memory)
        await clear_old_messages(user_id, keep_last=KEEP_AFTER_SUMMARY)

    except Exception as e:
        print(f"[Memory] Ошибка суммаризации для {user_id}: {e}")

async def maybe_summarize(client: AsyncOpenAI, user_id: int, model_name: str):
    """Проверяет, нужна ли суммаризация, и запускает её в фоне"""
    count = await get_message_count(user_id)
    if count >= SUMMARIZE_THRESHOLD:
        # Запускаем в фоне, чтобы не блокировать ответ пользователю
        asyncio.create_task(summarize_conversation(client, user_id, model_name))