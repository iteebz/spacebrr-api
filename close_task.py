#!/usr/bin/env python3
import sys
from pathlib import Path
from datetime import UTC, datetime

sys.path.insert(0, str(Path(__file__).parent))

from space.core.models import TaskStatus
from space.lib import store

def main():
    if len(sys.argv) < 2:
        print("usage: close_task.py <task_id_no_prefix>", file=sys.stderr)
        sys.exit(1)
    
    task_id = sys.argv[1]
    now = datetime.now(UTC).isoformat()
    
    with store.write() as conn:
        conn.execute(
            "UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?",
            (TaskStatus.DONE.value, now, task_id),
        )
    
    print(f"Closed t/{task_id}")

if __name__ == "__main__":
    main()
