#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from space.ledger import tasks
from space.core.models import TaskStatus

def main():
    if len(sys.argv) < 2:
        print("usage: close_task.py <task_id_no_prefix>", file=sys.stderr)
        sys.exit(1)
    
    task_id = sys.argv[1]
    tasks.set_status(task_id, TaskStatus.DONE)
    print(f"Closed t/{task_id}")

if __name__ == "__main__":
    main()
