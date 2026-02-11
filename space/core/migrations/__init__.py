"""One-shot repair: upgrades existing DBs to flattened 001_foundation schema.

All prior callable migrations (002-011) are folded into 001_foundation.sql.
"""

import sqlite3


def migration_018_health_suppressions(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(health_metrics)")
    columns = {row[1] for row in cursor.fetchall()}
    if "suppressions" not in columns:
        conn.execute(
            "ALTER TABLE health_metrics ADD COLUMN suppressions INTEGER NOT NULL DEFAULT 0"
        )


def migration_012_flatten_repair(conn: sqlite3.Connection) -> None:
    _add_summaries_table(conn)
    _widen_activity_check(conn)
    _ensure_triggers(conn)
    _mark_folded_migrations(conn)


def _add_summaries_table(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='summaries'"
    ).fetchone()
    if exists:
        return

    conn.executescript("""
        CREATE TABLE summaries (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
            project_id TEXT REFERENCES projects(id) ON DELETE RESTRICT,
            spawn_id TEXT REFERENCES spawns(id) ON DELETE SET NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            archived_at TEXT,
            deleted_at TEXT
        );
        CREATE INDEX idx_summaries_agent ON summaries(agent_id);
        CREATE INDEX idx_summaries_project ON summaries(project_id);
        CREATE INDEX idx_summaries_spawn ON summaries(spawn_id);
        CREATE INDEX idx_summaries_created ON summaries(created_at DESC);
        CREATE INDEX idx_summaries_archived ON summaries(archived_at);

        CREATE VIRTUAL TABLE summaries_fts USING fts5(id UNINDEXED, content);

        CREATE TRIGGER summaries_fts_ai AFTER INSERT ON summaries BEGIN
            INSERT INTO summaries_fts(id, content) VALUES (new.id, new.content);
        END;
        CREATE TRIGGER summaries_fts_ad AFTER DELETE ON summaries BEGIN
            DELETE FROM summaries_fts WHERE id = old.id;
        END;
        CREATE TRIGGER summaries_fts_au AFTER UPDATE ON summaries
        WHEN new.deleted_at IS NULL BEGIN
            DELETE FROM summaries_fts WHERE id = old.id;
            INSERT INTO summaries_fts(id, content) VALUES (new.id, new.content);
        END;
        CREATE TRIGGER summaries_fts_au_delete AFTER UPDATE ON summaries
        WHEN new.deleted_at IS NOT NULL AND old.deleted_at IS NULL BEGIN
            DELETE FROM summaries_fts WHERE id = old.id;
        END;
    """)


def _widen_activity_check(conn: sqlite3.Connection) -> None:
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='activity'"
    ).fetchone()
    if not schema or "'summary'" in schema[0]:
        return

    conn.execute("DROP TRIGGER IF EXISTS spawn_started")
    conn.execute("DROP TRIGGER IF EXISTS spawn_completed")
    conn.execute("DROP TRIGGER IF EXISTS spawn_failed")
    conn.execute("DROP TRIGGER IF EXISTS decision_created")
    conn.execute("DROP TRIGGER IF EXISTS decision_archived")
    conn.execute("DROP TRIGGER IF EXISTS insight_created")
    conn.execute("DROP TRIGGER IF EXISTS insight_archived")
    conn.execute("DROP TRIGGER IF EXISTS insight_linked")
    conn.execute("DROP TRIGGER IF EXISTS insight_resolved")
    conn.execute("DROP TRIGGER IF EXISTS task_created")
    conn.execute("DROP TRIGGER IF EXISTS task_status_change")
    conn.execute("DROP TRIGGER IF EXISTS reply_created")

    max_id = conn.execute("SELECT MAX(id) FROM activity").fetchone()[0] or 0

    conn.execute("""
        CREATE TABLE activity_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            spawn_id TEXT,
            primitive TEXT NOT NULL CHECK(primitive IN ('decision', 'insight', 'task', 'reply', 'spawn', 'summary')),
            primitive_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('created', 'archived', 'linked', 'claimed', 'released', 'completed', 'cancelled', 'resolved', 'rejected', 'started', 'failed')),
            field TEXT,
            before TEXT,
            after TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    conn.execute("""
        INSERT INTO activity_new (id, agent_id, spawn_id, primitive, primitive_id, action, field, before, after, created_at)
        SELECT id, agent_id, spawn_id, primitive, primitive_id, action, field, before, after, created_at
        FROM activity
    """)

    conn.execute("DROP TABLE activity")
    conn.execute("ALTER TABLE activity_new RENAME TO activity")
    conn.execute("CREATE INDEX idx_activity_agent ON activity(agent_id)")
    conn.execute("CREATE INDEX idx_activity_primitive ON activity(primitive, primitive_id)")
    conn.execute("CREATE INDEX idx_activity_created ON activity(created_at)")

    conn.execute(
        "UPDATE sqlite_sequence SET seq = ? WHERE name = 'activity'",
        (max_id,),
    )


_TRIGGERS = [
    """CREATE TRIGGER spawn_started AFTER INSERT ON spawns BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.id, 'spawn', NEW.id, 'started', NEW.created_at);
    END""",
    """CREATE TRIGGER spawn_completed AFTER UPDATE OF status ON spawns
    WHEN OLD.status = 'active' AND NEW.status = 'done' AND NEW.error IS NULL BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.id, 'spawn', NEW.id, 'completed', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
    END""",
    """CREATE TRIGGER spawn_failed AFTER UPDATE OF status ON spawns
    WHEN OLD.status = 'active' AND NEW.status = 'done' AND NEW.error IS NOT NULL BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, field, after, created_at)
        VALUES (NEW.agent_id, NEW.id, 'spawn', NEW.id, 'failed', 'error', NEW.error, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
    END""",
    """CREATE TRIGGER decision_created AFTER INSERT ON decisions BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'decision', NEW.id, 'created', NEW.created_at);
    END""",
    """CREATE TRIGGER decision_archived AFTER UPDATE OF archived_at ON decisions
    WHEN OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'decision', NEW.id, 'archived', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
    END""",
    """CREATE TRIGGER insight_created AFTER INSERT ON insights BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'created', NEW.created_at);
    END""",
    """CREATE TRIGGER insight_archived AFTER UPDATE OF archived_at ON insights
    WHEN OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'archived', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
    END""",
    """CREATE TRIGGER insight_linked AFTER UPDATE OF decision_id ON insights
    WHEN OLD.decision_id IS NULL AND NEW.decision_id IS NOT NULL BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, field, after, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'linked', 'decision_id', NEW.decision_id, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
    END""",
    """CREATE TRIGGER insight_resolved AFTER UPDATE OF open ON insights
    WHEN OLD.open = 1 AND NEW.open = 0 BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'resolved', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
    END""",
    """CREATE TRIGGER task_created AFTER INSERT ON tasks BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.creator_id, NEW.spawn_id, 'task', NEW.id, 'created', NEW.created_at);
    END""",
    """CREATE TRIGGER task_status_change AFTER UPDATE OF status ON tasks
    WHEN OLD.status != NEW.status BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, field, before, after, created_at)
        VALUES (
            COALESCE(NEW.assignee_id, NEW.creator_id), NEW.spawn_id, 'task', NEW.id,
            CASE NEW.status WHEN 'active' THEN 'claimed' WHEN 'done' THEN 'completed'
                WHEN 'cancelled' THEN 'cancelled' WHEN 'pending' THEN 'released' END,
            'status', OLD.status, NEW.status, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        );
    END""",
    """CREATE TRIGGER reply_created AFTER INSERT ON replies BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.author_id, NEW.spawn_id, 'reply', NEW.id, 'created', NEW.created_at);
    END""",
    """CREATE TRIGGER summary_created AFTER INSERT ON summaries BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'summary', NEW.id, 'created', NEW.created_at);
    END""",
    """CREATE TRIGGER summary_archived AFTER UPDATE OF archived_at ON summaries
    WHEN OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL BEGIN
        INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
        VALUES (NEW.agent_id, NEW.spawn_id, 'summary', NEW.id, 'archived', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
    END""",
]


def _ensure_triggers(conn: sqlite3.Connection) -> None:
    for sql in _TRIGGERS:
        name = sql.split("CREATE TRIGGER ")[1].split(" ")[0]
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
            (name,),
        ).fetchone()
        if not exists:
            conn.execute(sql)


def _mark_folded_migrations(conn: sqlite3.Connection) -> None:
    folded = [
        "002_project_tags",
        "002_search_fts",
        "002_spawn_inbox",
        "003_spawn_resume_count",
        "004_triggers_repair",
        "005_fts_backfill",
        "006_decision_references",
        "007_trigger_repair_v2",
        "008_rebuild_spawns_fts",
        "009_backfill_citations",
        "010_health_metrics",
        "010_summaries",
        "011_health_metrics",
    ]
    for name in folded:
        conn.execute("INSERT OR IGNORE INTO _migrations (name) VALUES (?)", (name,))
