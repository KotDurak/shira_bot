"""
Миграция 1: Добавление системы кредитов сообщений
Запуск: python migrations/migrate_1.py
"""
import asyncio
import sys
from pathlib import Path
import aiosqlite

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "shira_bot.db"


async def migrate():
    print(f"🔄 Запуск миграции для базы: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"❌ База данных не найдена: {DB_PATH}")
        print("💡 Сначала запусти бота: python main.py")
        sys.exit(1)

    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем таблицу users
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'") as cursor:
            if not await cursor.fetchone():
                print("❌ Таблица 'users' не найдена. Сначала запусти бота: python main.py")
                sys.exit(1)

        # Добавляем колонку message_credits
        async with db.execute("PRAGMA table_info(users)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]

            if "message_credits" not in columns:
                print("✅ Добавляем колонку message_credits...")
                await db.execute("ALTER TABLE users ADD COLUMN message_credits INTEGER DEFAULT 80")
                await db.commit()
                print("✅ Колонка добавлена")
            else:
                print("⏭️  Колонка message_credits уже есть")

        # Создаём таблицу payments
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
        await db.commit()
        print("✅ Таблица payments проверена")

        # Начисляем 80 бесплатных всем существующим
        await db.execute("UPDATE users SET message_credits = 80 WHERE message_credits IS NULL OR message_credits = 0")
        await db.commit()
        print("✅ Начислено 80 бесплатных сообщений всем пользователям")

    print("\n🎉 Миграция завершена!")


if __name__ == "__main__":
    asyncio.run(migrate())