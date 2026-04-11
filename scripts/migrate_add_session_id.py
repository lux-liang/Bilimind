"""
BiliMind 数据库迁移 — 添加 session_id 字段实现用户隔离 + 新增 GameScore/SRSRecord 表
"""
import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'bilibili_rag.db')


def migrate():
    db_path = os.path.abspath(DB_PATH)
    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}，将在首次启动时自动创建")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. 给现有表添加 session_id 字段
    tables_to_add_session = [
        'video_cache',
        'segments',
        'knowledge_nodes',
        'knowledge_edges',
        'node_segment_links',
    ]

    for table in tables_to_add_session:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN session_id VARCHAR(64)")
            print(f"✓ {table}: 添加 session_id 字段")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"- {table}: session_id 已存在，跳过")
            else:
                print(f"✗ {table}: {e}")

    # 2. 创建索引
    for table in tables_to_add_session:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_session_id ON {table}(session_id)")
            print(f"✓ {table}: 创建 session_id 索引")
        except Exception as e:
            print(f"- {table}: 索引创建跳过: {e}")

    # 3. 创建 game_scores 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(64) NOT NULL,
            score INTEGER DEFAULT 0,
            total_challenges INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            best_streak INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_scores_session ON game_scores(session_id)")
    print("✓ game_scores: 表创建完成")

    # 4. 创建 srs_records 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS srs_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(64) NOT NULL,
            node_id INTEGER NOT NULL,
            easiness_factor REAL DEFAULT 2.5,
            interval_days REAL DEFAULT 1.0,
            repetitions INTEGER DEFAULT 0,
            next_review_date DATETIME,
            last_review_date DATETIME,
            implicit_review BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_srs_session ON srs_records(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_srs_node ON srs_records(node_id)")
    print("✓ srs_records: 表创建完成")

    conn.commit()
    conn.close()
    print("\n迁移完成!")


if __name__ == '__main__':
    migrate()
