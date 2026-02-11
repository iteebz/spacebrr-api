#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "space" / "space-os"))

from space.core.types import ProjectId
from space.ledger import decisions, insights, projects, tasks


def fetch_ledger(project_id: str, limit: int = 50) -> list[dict]:
    pid = ProjectId(project_id)
    projects.set_request_scope(pid)
    
    items = []
    
    for task in tasks.fetch(limit=limit, project_id=pid):
        items.append({
            "type": "task",
            "id": task.id,
            "content": task.content,
            "agent_id": str(task.creator_id),
            "identity": "unknown",
            "created_at": task.created_at,
            "status": task.status.value if task.status else None,
        })
    
    for insight in insights.fetch(limit=limit, project_id=pid):
        items.append({
            "type": "insight",
            "id": insight.id,
            "content": insight.content,
            "agent_id": str(insight.agent_id),
            "identity": "unknown",
            "created_at": insight.created_at,
            "status": None,
        })
    
    for decision in decisions.fetch(limit=limit, project_id=pid):
        status = None
        if decision.actioned_at:
            status = "actioned"
        elif decision.rejected_at:
            status = "rejected"
        elif decision.committed_at:
            status = "committed"
        else:
            status = "proposed"
        
        items.append({
            "type": "decision",
            "id": decision.id,
            "content": decision.content,
            "agent_id": str(decision.agent_id),
            "identity": "unknown",
            "created_at": decision.created_at,
            "status": status,
        })
    
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[:limit]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: ledger.py <project_id> [limit]", file=sys.stderr)
        sys.exit(1)
    
    project_id = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    
    items = fetch_ledger(project_id, limit)
    print(json.dumps(items))
