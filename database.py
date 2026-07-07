import aiosqlite
import os
from typing import List, Optional
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "magnit_scanner.db")


async def init_db():
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


async def add_to_history(user_id: int, article: str, title: str,
                         price: str, in_stock: bool, store_code: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT INTO history (user_id, article, title, price, in_stock, store_code)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (user_id, article, title, price, int(in_stock), store_code)
        )
        await db.commit()


async def log_user_activity(user_id: int, username: str, first_name: str,
                            last_name: str, action: str, details: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO user_logs (user_id, username, first_name, last_name, action, details)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, action, details))
        await db.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_seen)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
        await db.commit()


async def get_user_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT COUNT(*) as count FROM users')
        total_users = (await cursor.fetchone())['count']

        cursor = await db.execute('''
            SELECT COUNT(*) as count FROM users
            WHERE last_seen >= datetime('now', '-1 day')
        ''')
        active_24h = (await cursor.fetchone())['count']

        cursor = await db.execute('SELECT COUNT(*) as count FROM history')
        total_searches = (await cursor.fetchone())['count']

        cursor = await db.execute('''
            SELECT u.user_id, u.username, u.first_name, COUNT(h.id) as searches
            FROM users u LEFT JOIN history h ON u.user_id = h.user_id
            GROUP BY u.user_id ORDER BY searches DESC LIMIT 10
        ''')
        top_users = await cursor.fetchall()

        return {
            'total_users': total_users,
            'active_24h': active_24h,
            'total_searches': total_searches,
            'top_users': [dict(row) for row in top_users]
        }


async def get_recent_logs(limit: int = 50) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM user_logs ORDER BY timestamp DESC LIMIT ?
        ''', (limit,))
        return [dict(row) for row in await cursor.fetchall()]


async def get_user_details(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = await cursor.fetchone()
        if not user:
            return None

        cursor = await db.execute('''
            SELECT * FROM history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10
        ''', (user_id,))
        history = await cursor.fetchall()

        cursor = await db.execute('''
            SELECT * FROM user_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10
        ''', (user_id,))
        logs = await cursor.fetchall()

        return {
            'user': dict(user),
            'history': [dict(row) for row in history],
            'logs': [dict(row) for row in logs]
        }


async def get_all_users() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT user_id FROM users')
        return [row[0] for row in await cursor.fetchall()]
