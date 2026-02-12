
import re
import sqlite3
from typing import Literal

CITATION_PATTERN = re.compile(r"\b(i|d)/([a-f0-9]{8})\b")

SourceType = Literal["insight", "decision", "reply", "spawn"]
TargetType = Literal["insight", "decision"]


def extract(text: str) -> list[tuple[TargetType, str]]:
    """Extract citation references from text. Returns list of (type, short_id)."""
    results: list[tuple[TargetType, str]] = []
    for match in CITATION_PATTERN.finditer(text):
        prefix, short_id = match.groups()
        target_type: TargetType = "insight" if prefix == "i" else "decision"
        results.append((target_type, short_id))
    return results


def store(
    conn: sqlite3.Connection,
    source_type: SourceType,
    source_id: str,
    text: str,
) -> int:
    """Extract and store citations from text. Returns count stored."""
    citations = extract(text)
    if not citations:
        return 0

    stored = 0
    for target_type, short_id in citations:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO citations (source_type, source_id, target_type, target_short_id)
                VALUES (?, ?, ?, ?)
                """,
                (source_type, source_id, target_type, short_id),
            )
            stored += conn.total_changes
        except sqlite3.Error:
            continue
    return stored


def count_refs(conn: sqlite3.Connection, target_type: TargetType, short_id: str) -> int:
    """Count citations pointing to a target."""
    row = conn.execute(
        "SELECT COUNT(*) FROM citations WHERE target_type = ? AND target_short_id = ?",
        (target_type, short_id),
    ).fetchone()
    return row[0] if row else 0


def refs_for_target(
    conn: sqlite3.Connection, target_type: TargetType, short_id: str
) -> list[tuple[SourceType, str]]:
    """Get all sources citing a target."""
    rows = conn.execute(
        "SELECT source_type, source_id FROM citations WHERE target_type = ? AND target_short_id = ?",
        (target_type, short_id),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]
