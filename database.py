import aiosqlite
import os
from typing import List, Optional
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "magnit_scanner.db")


async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица истории поисков
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
        
        # Таблица пользователей
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
        
        # Таблица логов активности
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                action TEXT NOT NULL,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
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


async def get_user_stats() -> dict:
    """Получение статистики по всем пользователям"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Всего пользователей
        cursor = await db.execute('SELECT COUNT(*) as count FROM users')
        total_users = (await cursor.fetchone())['count']
        
        # Активных за последние 24 часа
        cursor = await db.execute('''
            SELECT COUNT(*) as count FROM users 
            WHERE last_seen >= datetime('now', '-1 day')
        ''')
        active_24h = (await cursor.fetchone())['count']
        
        # Всего поисков
        cursor = await db.execute('SELECT COUNT(*) as count FROM history')
        total_searches = (await cursor.fetchone())['count']
        
        # Топ-10 активных пользователей
        cursor = await db.execute('''
            SELECT u.user_id, u.username, u.first_name, COUNT(h.id) as searches
            FROM users u
            LEFT JOIN history h ON u.user_id = h.user_id
            GROUP BY u.user_id
            ORDER BY searches DESC
            LIMIT 10
        ''')
        top_users = await cursor.fetchall()
        
        return {
            'total_users': total_users,
            'active_24h': active_24h,
            'total_searches': total_searches,
            'top_users': [dict(row) for row in top_users]
        }


async def get_recent_logs(limit: int = 50) -> list:
    """Получение последних логов"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM user_logs 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_user_details(user_id: int) -> dict:
    """Получение детальной информации о пользователе"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Информация о пользователе
        cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = await cursor.fetchone()
        
        if not user:
            return None
        
        # История поисков
        cursor = await db.execute('''
            SELECT * FROM history 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 10
        ''', (user_id,))
        history = await cursor.fetchall()
        
        # Последние действия
        cursor = await db.execute('''
            SELECT * FROM user_logs 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 10
        ''', (user_id,))
        logs = await cursor.fetchall()
        
        return {
            'user': dict(user),
            'history': [dict(row) for row in history],
            'logs': [dict(row) for row in logs]
        }


async def log_user_activity(user_id: int, username: str, first_name: str, 
                            last_name: str, action: str, details: str = ""):
    """Логирует активность пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Добавляем запись в логи
        await db.execute('''
            INSERT INTO user_logs (user_id, username, first_name, last_name, action, details)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, action, details))
        
        # Обновляем информацию о пользователе
        await db.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_seen)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
        
        await db.commit()


async def get_all_users() -> List[int]:
    """Получение списка всех user_id для рассылки"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT user_id FROM users')
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
