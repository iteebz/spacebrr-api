import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from space.core import ids
from space.core.errors import NotFoundError, ValidationError
from space.core.models import Reply
from space.core.types import AgentId, ArtifactType, ProjectId, ReplyId, SpawnId
from space.ledger import artifacts, inbox
from space.lib import citations, store

MENTION_PATTERN = re.compile(r"(?<!\w)@(\w+)")


def _known_identities() -> set[str]:
    """Fetch known agent handles via SQL."""
    with store.ensure() as conn:
        rows = conn.execute("SELECT handle FROM agents WHERE deleted_at IS NULL").fetchall()
    return {r["handle"] for r in rows} | {"human"}


def parse_mentions(content: str, validate: bool = True) -> list[str]:
    raw = MENTION_PATTERN.findall(content)
    if not validate:
        return raw
    known = _known_identities()
    return [m for m in raw if m in known]


def validate_mentions(content: str) -> tuple[list[str], list[str]]:
    """Return (valid, invalid) mentions from content."""
    raw = MENTION_PATTERN.findall(content)
    known = _known_identities()
    valid = [m for m in raw if m in known]
    invalid = [m for m in raw if m not in known]
    return valid, invalid


def _expand_aliases(mentions: list[str]) -> list[str]:
    if "human" not in mentions:
        return mentions
    with store.ensure() as conn:
        rows = conn.execute(
            "SELECT handle FROM agents WHERE type = 'human' AND deleted_at IS NULL"
        ).fetchall()
    human_handles = [r["handle"] for r in rows]
    return [m for m in mentions if m != "human"] + human_handles


def resolve_parent_type(parent_id: str) -> tuple[ArtifactType, str]:
    return artifacts.resolve(parent_id)


def create_by_ref(
    ref: str,
    author_id: AgentId,
    content: str,
    spawn_id: SpawnId | None = None,
) -> Reply:
    """Create a reply using a reference like 'i/abcd1234'."""
    if "/" not in ref:
        raise ValidationError(f"Invalid reference format: {ref} (expected prefix/id)")

    _prefix, short_id = ref.split("/", 1)
    parent_type, full_parent_id = resolve_parent_type(short_id)
    project_id = artifacts.get_project_id(parent_type, full_parent_id)

    return create(
        parent_id=full_parent_id,
        author_id=author_id,
        content=content,
        spawn_id=spawn_id,
        project_id=project_id,
    )


def create(
    parent_id: str,
    author_id: AgentId,
    content: str,
    spawn_id: SpawnId | None = None,
    project_id: ProjectId | None = None,
    images: list[str] | None = None,
) -> Reply:
    parent_type, full_parent_id = resolve_parent_type(parent_id)
    mentions = _expand_aliases(parse_mentions(content))

    reply_id = ReplyId(ids.generate("replies"))
    now = datetime.now(UTC).isoformat()

    with store.write() as conn:
        store.unarchive("agents", author_id, conn)
        conn.execute(
            "INSERT INTO replies (id, parent_type, parent_id, author_id, spawn_id, project_id, content, mentions, images, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reply_id,
                parent_type,
                full_parent_id,
                author_id,
                spawn_id,
                project_id,
                content,
                json.dumps(mentions) if mentions else None,
                json.dumps(images) if images else None,
                now,
            ),
        )
        citations.store(conn, "reply", reply_id, content)
    return get(reply_id)


def get(reply_id: ReplyId) -> Reply:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM replies WHERE id = ?", (reply_id,)).fetchone()
        if not row:
            raise NotFoundError(reply_id)
        return store.from_row(row, Reply)


def delete(reply_id: ReplyId) -> None:
    artifacts.soft_delete("replies", reply_id, "Reply")


def fetch_for_parent(parent_type: ArtifactType, parent_id: str) -> list[Reply]:
    with store.ensure() as conn:
        rows = conn.execute(
            "SELECT * FROM replies WHERE parent_type = ? AND parent_id = ? AND deleted_at IS NULL ORDER BY created_at",
            (parent_type, parent_id),
        ).fetchall()
    return [store.from_row(row, Reply) for row in rows]


def fetch_for_parents(parent_type: ArtifactType, parent_ids: list[str]) -> dict[str, list[Reply]]:
    if not parent_ids:
        return {}
    result: dict[str, list[Reply]] = {pid: [] for pid in parent_ids}
    with store.ensure() as conn:
        rows = (
            store.q("replies")
            .not_deleted()
            .where("parent_type = ?", parent_type)
            .where_in("parent_id", parent_ids)
            .order("created_at")
            .execute(conn)
        )
    for row in rows:
        reply = store.from_row(row, Reply)
        result[reply.parent_id].append(reply)
    return result


@dataclass
class InboxItem:
    reply: Reply
    parent_content: str
    parent_identity: str


def inbox_with_context(agent_identity: str) -> list[InboxItem]:
    replies_list = inbox.fetch_replies(agent_identity)
    if not replies_list:
        return []

    items = []
    with store.ensure() as conn:
        for reply in replies_list:
            table = f"{reply.parent_type}s"
            row = conn.execute(
                f"SELECT content, agent_id FROM {table} WHERE id = ?",  # noqa: S608
                (reply.parent_id,),
            ).fetchone()
            if row:
                agent_row = conn.execute(
                    "SELECT identity FROM agents WHERE id = ?",
                    (row["agent_id"],),
                ).fetchone()
                items.append(
                    InboxItem(
                        reply=reply,
                        parent_content=row["content"],
                        parent_identity=agent_row["identity"] if agent_row else "unknown",
                    )
                )
    return items


@dataclass
class ThreadState:
    reply_count: int
    awaiting_human: bool
    stale: bool
    last_reply_at: str | None
    unique_authors: int = 0


def thread_state(parent_type: ArtifactType, parent_id: str) -> ThreadState:
    """Compute thread state with SQL for author types."""
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT r.id, r.mentions, r.created_at, a.type as author_type, r.author_id
            FROM replies r
            LEFT JOIN agents a ON r.author_id = a.id
            WHERE r.parent_type = ? AND r.parent_id = ? AND r.deleted_at IS NULL
            ORDER BY r.created_at ASC
            """,
            (parent_type, parent_id),
        ).fetchall()

    reply_count = len(rows)
    if not rows:
        return ThreadState(reply_count=0, awaiting_human=False, stale=False, last_reply_at=None)

    last_reply_at = rows[-1]["created_at"]
    stale = False
    if last_reply_at:
        last_time = datetime.fromisoformat(last_reply_at)
        stale = datetime.now(UTC) - last_time > timedelta(hours=24)

    awaiting_human = False
    unique_authors: set[str] = set()
    for row in reversed(rows):
        mentions = json.loads(row["mentions"]) if row["mentions"] else []
        if "human" in mentions:
            awaiting_human = True
            break
        if row["author_type"] == "human":
            awaiting_human = False
            break
        unique_authors.add(row["author_id"])

    return ThreadState(
        reply_count=reply_count,
        awaiting_human=awaiting_human,
        stale=stale,
        last_reply_at=last_reply_at,
        unique_authors=len(unique_authors),
    )
