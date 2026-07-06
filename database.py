import aiosqlite
import os
from typing import List, Optional
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "magnit_scanner.db")

async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                article TEXT NOT NULL,
                title TEXT NOT NULL,
                price TEXT,
                in_stock INTEGER,
                store_code TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME
            )
        ''')
        await db.commit()

async def add_user(user_id: int, username: Optional[str] = None, 
                   first_name: Optional[str] = None, 
                   last_name: Optional[str] = None):
    """Добавление или обновление пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_seen)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
        await db.commit()

async def add_to_history(user_id: int, article: str, title: str, 
                         price: str, in_stock: bool, store_code: str = ""):
    """Добавление записи в историю поиска"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT INTO history (user_id, article, title, price, in_stock, store_code) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (user_id, article, title, price, int(in_stock), store_code)
        )
        await db.commit()

async def get_history(user_id: int, limit: int = 20) -> List[dict]:
    """Получение истории поиска пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            '''SELECT * FROM history 
               WHERE user_id = ? 
               ORDER BY timestamp DESC 
               LIMIT ?''',
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def clear_history(user_id: int):
    """Очистка истории пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'DELETE FROM history WHERE user_id = ?',
            (user_id,)
        )
        await db.commit()

async def get_user_stats(user_id: int) -> dict:
    """Получение статистики пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Всего поисков
        cursor = await db.execute(
            'SELECT COUNT(*) as count FROM history WHERE user_id = ?',
            (user_id,)
        )
        total_searches = (await cursor.fetchone())['count']
        
        # Найдено товаров
        cursor = await db.execute(
            'SELECT COUNT(*) as count FROM history WHERE user_id = ? AND in_stock = 1',
            (user_id,)
        )
        found_items = (await cursor.fetchone())['count']
        
        return {
            'total_searches': total_searches,
            'found_items': found_items,
            'not_found_items': total_searches - found_items
        }