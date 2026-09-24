import aiosqlite
from typing import Optional, List, Tuple

DB_PATH = "shira_bot.db"

FREE_MESSAGES_LIMIT = 80


async def init_db():
    """Инициализация БД с WAL-режимом"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA cache_size=-8000;")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                long_term_memory TEXT DEFAULT '',
                message_credits INTEGER DEFAULT 80,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                telegram_charge_id TEXT,
                provider_charge_id TEXT,
                status TEXT DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_time ON messages(user_id, timestamp)")
        await db.commit()


async def get_or_create_user(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT user_id, username, first_name, long_term_memory, message_credits FROM users WHERE user_id = ?",
                (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "username": row[1],
                    "first_name": row[2],
                    "long_term_memory": row[3] or "",
                    "message_credits": row[4] if row[4] is not None else FREE_MESSAGES_LIMIT
                }

        # Создаём нового пользователя с 80 бесплатными сообщениями
        await db.execute(
            "INSERT INTO users (user_id, username, first_name, message_credits) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, FREE_MESSAGES_LIMIT)
        )
        await db.commit()
        return {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "long_term_memory": "",
            "message_credits": FREE_MESSAGES_LIMIT
        }


async def save_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()


async def get_recent_messages(user_id: int, limit: int = 10) -> List[Tuple[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return list(reversed([(row[0], row[1]) for row in rows]))


async def get_all_messages_for_summary(user_id: int) -> List[Tuple[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id ASC",
                (user_id,)
        ) as cursor:
            return [(row[0], row[1]) for row in await cursor.fetchall()]


async def get_message_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def clear_old_messages(user_id: int, keep_last: int = 6):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM messages 
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
            )
        """, (user_id, user_id, keep_last))
        await db.commit()


async def update_long_term_memory(user_id: int, memory: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET long_term_memory = ? WHERE user_id = ?", (memory, user_id))
        await db.commit()


async def get_message_credits(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT message_credits FROM users WHERE user_id = ?",
                (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] is not None else 0


async def use_message_credit(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT message_credits FROM users WHERE user_id = ?",
                (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] is None or row[0] <= 0:
                return False

        await db.execute(
            "UPDATE users SET message_credits = message_credits - 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
        return True


async def add_message_credits(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET message_credits = message_credits + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()


async def save_payment(user_id: int, amount: int, telegram_charge_id: str, provider_charge_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (user_id, amount, telegram_charge_id, provider_charge_id) VALUES (?, ?, ?, ?)",
            (user_id, amount, telegram_charge_id, provider_charge_id)
        )
        await db.commit()