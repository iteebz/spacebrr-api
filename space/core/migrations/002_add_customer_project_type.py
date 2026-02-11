"""Add customer project type and fields for SaaS multi-tenancy."""

import sqlite3


def migration_002_add_customer_project_type(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE projects_new (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL CHECK(type IN ('standard', 'proto', 'customer')),
            repo_path TEXT UNIQUE,
            github_login TEXT,
            repo_url TEXT,
            provisioned_at TEXT,
            color TEXT,
            icon TEXT,
            tags TEXT,
            created_at TEXT NOT NULL,
            archived_at TEXT
        )
    """)

    conn.execute("""
        INSERT INTO projects_new
        SELECT id, name, type, repo_path, NULL, NULL, NULL, color, icon, tags, created_at, archived_at
        FROM projects
    """)

    conn.execute("DROP TABLE projects")
    conn.execute("ALTER TABLE projects_new RENAME TO projects")

    conn.execute("CREATE INDEX idx_projects_github_login ON projects(github_login)")
    conn.execute("CREATE INDEX idx_projects_type ON projects(type)")

    conn.commit()
