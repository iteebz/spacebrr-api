#!/usr/bin/env python3
import sys
from datetime import UTC, datetime

from space import core
from space.ledger import projects
from space.lib import store


def main() -> None:
    if len(sys.argv) < 8:
        sys.stderr.write("usage: webhook_pr.py EVENT_TYPE PR_NUM REPO_NAME AUTHOR MERGED_BY CREATED_AT MERGED_AT\n")
        sys.exit(1)
    
    event_type = sys.argv[1]
    pr_number = int(sys.argv[2])
    repo_name = sys.argv[3]
    author = sys.argv[4]
    merged_by = sys.argv[5] or None
    created_at = sys.argv[6]
    merged_at = sys.argv[7] or None
    
    if event_type not in ("opened", "merged", "closed"):
        sys.stderr.write(f"invalid event_type: {event_type}\n")
        sys.exit(1)
    
    with store.ensure() as conn:
        project_row = conn.execute(
            "SELECT id FROM projects WHERE repo_url LIKE ? AND type = 'customer' LIMIT 1",
            (f"%{repo_name}%",),
        ).fetchone()
        
        if not project_row:
            sys.stderr.write(f"no customer project found for repo: {repo_name}\n")
            sys.exit(1)
        
        project_id = project_row[0]
        event_id = core.ids.generate("pr_events")
        now = datetime.now(UTC).isoformat()
        
        with store.write() as write_conn:
            write_conn.execute(
                """
                INSERT OR IGNORE INTO pr_events
                (id, project_id, event_type, pr_number, repo_name, author, merged_by, created_at, merged_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, project_id, event_type, pr_number, repo_name, author, merged_by, created_at, merged_at),
            )
    
    sys.stdout.write(f"recorded {event_type} event for PR#{pr_number} in {repo_name}\n")


if __name__ == "__main__":
    main()
