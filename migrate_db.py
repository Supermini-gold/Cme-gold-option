import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_data.db')

def migrate():
    if not os.path.exists(DB_PATH):
        print("DB file not found, nothing to migrate.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(analysis_history)")
    columns = [row[1] for row in cursor.fetchall()]
    
    new_columns = [
        ('z5_score', 'REAL'),
        ('gex_flip_zone', 'REAL'),
        ('max_pain', 'REAL'),
        ('range_high_1sd', 'REAL'),
        ('range_low_1sd', 'REAL'),
        ('was_accurate', 'BOOLEAN')
    ]
    
    for col_name, col_type in new_columns:
        if col_name not in columns:
            print(f"Adding column {col_name}...")
            try:
                cursor.execute(f"ALTER TABLE analysis_history ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                print(f"Error adding {col_name}: {e}")
    
    # Also check schedules table for new toggles
    cursor.execute("PRAGMA table_info(schedules)")
    sched_columns = [row[1] for row in cursor.fetchall()]
    
    new_sched_cols = [
        ('reminders_enabled', 'BOOLEAN DEFAULT 1'),
        ('alerts_enabled', 'BOOLEAN DEFAULT 1')
    ]
    
    for col_name, col_type in new_sched_cols:
        if col_name not in sched_columns:
            print(f"Adding column {col_name} to schedules...")
            try:
                cursor.execute(f"ALTER TABLE schedules ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                print(f"Error adding {col_name} to schedules: {e}")

    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
