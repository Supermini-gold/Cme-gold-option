import aiosqlite
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_data.db')


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    result_text TEXT NOT NULL,
                    num_images INTEGER DEFAULT 3,
                    summary TEXT,
                    z5_score REAL,
                    gex_flip_zone REAL,
                    max_pain REAL
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS schedules (
                    user_id INTEGER PRIMARY KEY,
                    interval_hours INTEGER NOT NULL DEFAULT 3,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.commit()

    async def save_analysis(self, user_id, result_text, num_images=3, summary=None, z5=None, gex=None, max_pain=None):
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                'INSERT INTO analysis_history (user_id, result_text, num_images, summary, z5_score, gex_flip_zone, max_pain) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (user_id, result_text, num_images, summary, z5, gex, max_pain)
            )
            await conn.commit()
            return cursor.lastrowid

    async def get_history(self, user_id, limit=10):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT id, timestamp, summary, num_images FROM analysis_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?',
                (user_id, limit)
            )
            return await cursor.fetchall()

    async def get_analysis_by_id(self, analysis_id, user_id=None):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            if user_id:
                cursor = await conn.execute(
                    'SELECT * FROM analysis_history WHERE id = ? AND user_id = ?',
                    (analysis_id, user_id)
                )
            else:
                cursor = await conn.execute(
                    'SELECT * FROM analysis_history WHERE id = ?',
                    (analysis_id,)
                )
            return await cursor.fetchone()

    async def get_latest_analysis(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM analysis_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1',
                (user_id,)
            )
            return await cursor.fetchone()

    async def save_schedule(self, user_id, interval_hours=3):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                '''INSERT INTO schedules (user_id, interval_hours, is_active)
                   VALUES (?, ?, 1)
                   ON CONFLICT(user_id) DO UPDATE SET
                   interval_hours = excluded.interval_hours, is_active = 1''',
                (user_id, interval_hours)
            )
            await conn.commit()

    async def get_schedule(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM schedules WHERE user_id = ? AND is_active = 1',
                (user_id,)
            )
            return await cursor.fetchone()

    async def delete_schedule(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                'UPDATE schedules SET is_active = 0 WHERE user_id = ?',
                (user_id,)
            )
            await conn.commit()

    async def get_all_active_schedules(self):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM schedules WHERE is_active = 1'
            )
            return await cursor.fetchall()

    async def cleanup_old_history(self, user_id, keep_count=20):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('''
                DELETE FROM analysis_history
                WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM analysis_history
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                )
            ''', (user_id, user_id, keep_count))
            await conn.commit()
