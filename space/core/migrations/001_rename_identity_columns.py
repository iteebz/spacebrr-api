
import sqlite3


def migration_001_rename_identity_columns(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE agents RENAME COLUMN identity TO handle")
    conn.execute("ALTER TABLE agents RENAME COLUMN constitution TO identity")
    conn.execute("DROP INDEX IF EXISTS idx_agents_identity")
    conn.execute("CREATE INDEX idx_agents_handle ON agents(handle)")
    conn.commit()
