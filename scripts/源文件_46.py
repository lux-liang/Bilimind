"""
知映 ZhiYing — 数据库迁移
新增 Concept/Claim/ConceptRelation/CrossVideoAlignment/UserMastery 表
扩展 Segment 表（knowledge_density, is_peak）
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'bilibili_rag.db')


def migrate():
    db_path = os.path.abspath(DB_PATH)
    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}，将在首次启动时自动创建")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Concepts 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(64),
            name VARCHAR(200) NOT NULL,
            normalized_name VARCHAR(200),
            definition TEXT,
            difficulty INTEGER DEFAULT 1,
            source_count INTEGER DEFAULT 1,
            video_count INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_concepts_session ON concepts(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_concepts_name ON concepts(normalized_name)")
    print("✓ concepts 表创建完成")

    # 2. Claims 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(64),
            concept_id INTEGER NOT NULL,
            statement TEXT NOT NULL,
            claim_type VARCHAR(30) DEFAULT 'explanation',
            confidence REAL DEFAULT 0.5,
            segment_id INTEGER,
            video_bvid VARCHAR(20),
            start_time REAL,
            end_time REAL,
            raw_text TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_session ON claims(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_concept ON claims(concept_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_video ON claims(video_bvid)")
    print("✓ claims 表创建完成")

    # 3. ConceptRelation 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS concept_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(64),
            source_concept_id INTEGER NOT NULL,
            target_concept_id INTEGER NOT NULL,
            relation_type VARCHAR(30) NOT NULL,
            confidence REAL DEFAULT 0.5,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_crel_session ON concept_relations(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_crel_source ON concept_relations(source_concept_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_crel_target ON concept_relations(target_concept_id)")
    print("✓ concept_relations 表创建完成")

    # 4. CrossVideoAlignment 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cross_video_alignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(64),
            concept_id INTEGER NOT NULL,
            claim_a_id INTEGER NOT NULL,
            claim_b_id INTEGER NOT NULL,
            alignment_type VARCHAR(30) NOT NULL,
            explanation TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cva_session ON cross_video_alignments(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cva_concept ON cross_video_alignments(concept_id)")
    print("✓ cross_video_alignments 表创建完成")

    # 5. UserMastery 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_mastery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(64) NOT NULL,
            concept_id INTEGER NOT NULL,
            mastery_level INTEGER DEFAULT 0,
            last_reviewed_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mastery_session ON user_mastery(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mastery_concept ON user_mastery(concept_id)")
    print("✓ user_mastery 表创建完成")

    # 6. Segment 表扩展
    for col, col_type in [("knowledge_density", "REAL"), ("is_peak", "BOOLEAN DEFAULT 0")]:
        try:
            cursor.execute(f"ALTER TABLE segments ADD COLUMN {col} {col_type}")
            print(f"✓ segments: 添加 {col} 字段")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"- segments: {col} 已存在，跳过")

    conn.commit()
    conn.close()
    print("\n知映数据库迁移完成!")


if __name__ == '__main__':
    migrate()
