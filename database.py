import aiosqlite
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_data.db')


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as conn:
            # Create tables
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    result_text TEXT NOT NULL,
                    num_images INTEGER DEFAULT 3,
                    summary TEXT
                )
            ''')
            
            # Migration: Add missing columns to analysis_history
            cursor = await conn.execute("PRAGMA table_info(analysis_history)")
            existing_cols = [row[1] for row in await cursor.fetchall()]
            
            migrations = [
                ('z5_score', 'REAL'),
                ('gex_flip_zone', 'REAL'),
                ('max_pain', 'REAL'),
                ('range_high_1sd', 'REAL'),
                ('range_low_1sd', 'REAL'),
                ('was_accurate', 'BOOLEAN')
            ]
            
            for col_name, col_type in migrations:
                if col_name not in existing_cols:
                    await conn.execute(f"ALTER TABLE analysis_history ADD COLUMN {col_name} {col_type}")

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS schedules (
                    user_id INTEGER PRIMARY KEY,
                    interval_hours INTEGER NOT NULL DEFAULT 3,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Migration: Add missing columns to schedules
            cursor = await conn.execute("PRAGMA table_info(schedules)")
            sched_cols = [row[1] for row in await cursor.fetchall()]
            if 'reminders_enabled' not in sched_cols:
                await conn.execute("ALTER TABLE schedules ADD COLUMN reminders_enabled BOOLEAN DEFAULT 1")
            if 'alerts_enabled' not in sched_cols:
                await conn.execute("ALTER TABLE schedules ADD COLUMN alerts_enabled BOOLEAN DEFAULT 1")

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS performance_stats (
                    user_id INTEGER PRIMARY KEY,
                    total_analyzed INTEGER DEFAULT 0,
                    total_accurate INTEGER DEFAULT 0,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS macro_data (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_alert_state (
                    user_id INTEGER NOT NULL,
                    date_str TEXT NOT NULL,
                    max_atr_alerted INTEGER DEFAULT 0,
                    sd_alert_state TEXT,
                    PRIMARY KEY (user_id, date_str)
                )
            ''')
            await conn.commit()

    async def save_analysis(self, user_id, result_text, num_images=3, summary=None, z5=None, gex=None, max_pain=None, high_1sd=None, low_1sd=None):
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                '''INSERT INTO analysis_history 
                   (user_id, result_text, num_images, summary, z5_score, gex_flip_zone, max_pain, range_high_1sd, range_low_1sd) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (user_id, result_text, num_images, summary, z5, gex, max_pain, high_1sd, low_1sd)
            )
            await conn.commit()
            return cursor.lastrowid

    async def update_accuracy(self, analysis_id, was_accurate):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                'UPDATE analysis_history SET was_accurate = ? WHERE id = ?',
                (was_accurate, analysis_id)
            )
            
            # Update stats
            cursor = await conn.execute('SELECT user_id FROM analysis_history WHERE id = ?', (analysis_id,))
            row = await cursor.fetchone()
            if row:
                user_id = row[0]
                await conn.execute('''
                    INSERT INTO performance_stats (user_id, total_analyzed, total_accurate)
                    VALUES (?, 1, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    total_analyzed = total_analyzed + 1,
                    total_accurate = total_accurate + ?,
                    last_updated = CURRENT_TIMESTAMP
                ''', (user_id, 1 if was_accurate else 0, 1 if was_accurate else 0))
            
            await conn.commit()

    async def save_macro_data(self, key, value):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                '''INSERT INTO macro_data (key, value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value, updated_at = CURRENT_TIMESTAMP''',
                (key, value)
            )
            await conn.commit()

    async def get_macro_data(self, key):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM macro_data WHERE key = ?',
                (key,)
            )
            return await cursor.fetchone()

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

    async def save_schedule(self, user_id, interval_hours=3, reminders=True, alerts=True):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                '''INSERT INTO schedules (user_id, interval_hours, is_active, reminders_enabled, alerts_enabled)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   interval_hours = excluded.interval_hours, 
                   is_active = 1,
                   reminders_enabled = excluded.reminders_enabled,
                   alerts_enabled = excluded.alerts_enabled''',
                (user_id, interval_hours, reminders, alerts)
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

    async def add_alert(self, user_id, symbol, condition, threshold):
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                '''INSERT INTO user_alerts (user_id, symbol, condition, threshold, is_active)
                   VALUES (?, ?, ?, ?, 1)''',
                (user_id, symbol, condition, threshold)
            )
            await conn.commit()
            return cursor.lastrowid

    async def get_alerts(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM user_alerts WHERE user_id = ? AND is_active = 1',
                (user_id,)
            )
            return await cursor.fetchall()

    async def delete_alert(self, alert_id, user_id=None):
        async with aiosqlite.connect(self.db_path) as conn:
            if user_id:
                await conn.execute(
                    'UPDATE user_alerts SET is_active = 0 WHERE id = ? AND user_id = ?',
                    (alert_id, user_id)
                )
            else:
                await conn.execute(
                    'UPDATE user_alerts SET is_active = 0 WHERE id = ?',
                    (alert_id,)
                )
            await conn.commit()

    async def get_all_active_alerts(self):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM user_alerts WHERE is_active = 1'
            )
            return await cursor.fetchall()

    async def get_unevaluated_history(self):
        """Fetch analyses that are at least 1 day old and not yet evaluated"""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute('''
                SELECT id, user_id, timestamp, summary, z5_score 
                FROM analysis_history 
                WHERE was_accurate IS NULL 
                AND timestamp <= datetime('now', '-1 day')
            ''')
            return await cursor.fetchall()

    async def get_performance_stats(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM performance_stats WHERE user_id = ?',
                (user_id,)
            )
            return await cursor.fetchone()

    async def get_daily_alert_state(self, user_id, date_str):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                'SELECT * FROM daily_alert_state WHERE user_id = ? AND date_str = ?',
                (user_id, date_str)
            )
            return await cursor.fetchone()

    async def update_daily_alert_state(self, user_id, date_str, max_atr=None, sd_state=None):
        async with aiosqlite.connect(self.db_path) as conn:
            # Upsert
            await conn.execute(
                '''INSERT INTO daily_alert_state (user_id, date_str, max_atr_alerted, sd_alert_state)
                   VALUES (?, ?, COALESCE(?, 0), ?)
                   ON CONFLICT(user_id, date_str) DO UPDATE SET
                   max_atr_alerted = COALESCE(?, max_atr_alerted),
                   sd_alert_state = COALESCE(?, sd_alert_state)''',
                (user_id, date_str, max_atr, sd_state, max_atr, sd_state)
            )
            await conn.commit()
