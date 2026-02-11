"""Unified search across all primitives via FTS5."""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from space.core.errors import NotFoundError, ValidationError
from space.core.types import ProjectId
from space.ledger import projects
from space.lib import store
from space.lib.commands import echo, fail, space_cmd
from space.lib.display.format import truncate


@dataclass
class SearchResult:
    source: str
    content: str
    reference: str
    timestamp: str | None = None
    weight: int = 0
    metadata: dict[str, Any] | None = None


@dataclass
class SourceConfig:
    table: str
    fts_table: str
    fts_key: str
    content_field: str
    weight: int
    metadata_fields: list[str]
    soft_delete: str | None = None
    extra_filter: str | None = None


_SOURCES: dict[str, SourceConfig] = {
    "tasks": SourceConfig(
        table="tasks",
        fts_table="tasks_fts",
        fts_key="id",
        content_field="content",
        weight=40,
        metadata_fields=["status"],
        soft_delete="deleted_at",
        extra_filter="status NOT IN ('done', 'cancelled')",
    ),
    "spawns": SourceConfig(
        table="spawns",
        fts_table="spawns_fts",
        fts_key="id",
        content_field="summary",
        weight=35,
        metadata_fields=["status"],
    ),
    "insights": SourceConfig(
        table="insights",
        fts_table="insights_fts",
        fts_key="id",
        content_field="content",
        weight=50,
        soft_delete="deleted_at",
        metadata_fields=["domain"],
    ),
    "decisions": SourceConfig(
        table="decisions",
        fts_table="decisions_fts",
        fts_key="id",
        content_field="content",
        weight=45,
        soft_delete="deleted_at",
        metadata_fields=["rationale"],
    ),
    "replies": SourceConfig(
        table="replies",
        fts_table="replies_fts",
        fts_key="id",
        content_field="content",
        weight=25,
        soft_delete="deleted_at",
        metadata_fields=["parent_type"],
    ),
}

SOURCES = tuple(_SOURCES.keys())


def _fts_escape(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _validate_term(term: str, max_len: int = 256) -> None:
    if len(term) > max_len:
        raise ValidationError(f"Search term too long (max {max_len} chars)")


def _resolve_scopes(scope: str | list[str]) -> list[str]:
    if scope == "all":
        return list(SOURCES)
    if isinstance(scope, str):
        return [scope]
    return scope


def _iter_source_configs(scopes: list[str]) -> list[tuple[str, SourceConfig]]:
    return [(source_name, cfg) for source_name in scopes if (cfg := _SOURCES.get(source_name))]


def _sort_key(result: SearchResult) -> tuple[int, str]:
    return result.weight, result.timestamp or ""


def _search_source(
    source_name: str,
    cfg: SourceConfig,
    term: str,
    limit: int,
    project_id: ProjectId | None,
    after: str | None = None,
    before: str | None = None,
) -> list[SearchResult]:
    conditions = [
        f"t.{cfg.fts_key} IN (SELECT {cfg.fts_key} FROM {cfg.fts_table} WHERE {cfg.fts_table} MATCH ?)"  # noqa: S608
    ]
    params: list[str | int] = [_fts_escape(term)]

    if cfg.soft_delete:
        conditions.append(f"t.{cfg.soft_delete} IS NULL")
    if cfg.extra_filter:
        conditions.append(f"t.{cfg.extra_filter}")
    if project_id and source_name != "spawns":
        conditions.append("t.project_id = ?")
        params.append(project_id)
    if after:
        conditions.append("t.created_at > ?")
        params.append(after)
    if before:
        conditions.append("t.created_at < ?")
        params.append(before)

    where = " AND ".join(conditions)
    sql = f"SELECT t.* FROM {cfg.table} t WHERE {where} ORDER BY t.created_at DESC LIMIT ?"  # noqa: S608
    params.append(limit)

    with store.ensure() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        SearchResult(
            source=source_name,
            content=r[cfg.content_field] or "",
            reference=f"{source_name[0]}/{r['id'][:8]}",
            timestamp=r["created_at"],
            weight=cfg.weight,
            metadata={f: r[f] for f in cfg.metadata_fields},
        )
        for r in rows
    ]


def query(
    term: str,
    scope: str | list[str] = "all",
    after: str | None = None,
    before: str | None = None,
    limit: int = 20,
    project_id: ProjectId | None = None,
) -> list[SearchResult]:
    _validate_term(term)

    scopes = _resolve_scopes(scope)
    per_source_limit = limit * 2 if len(scopes) > 1 else limit

    results = [
        result
        for source_name, cfg in _iter_source_configs(scopes)
        for result in _search_source(
            source_name,
            cfg,
            term,
            per_source_limit,
            project_id,
            after,
            before,
        )
    ]
    results.sort(key=_sort_key, reverse=True)
    return results[:limit]


# CLI --------------------------------------------------------------------------


def _parse_date(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()
    except ValueError as e:
        raise ValidationError(
            f"Invalid date format: {date_str}. Use ISO format (YYYY-MM-DD)"
        ) from e


def _recent_to_after(days: int) -> str:
    dt = datetime.now(UTC) - timedelta(days=days)
    return dt.isoformat()


def _format_result(result: SearchResult, verbose: bool = False) -> str:
    lines = []
    source_tag = f"[{result.source}]"
    ref = result.reference

    content = result.content.replace("\n", " ").strip()
    if not verbose:
        content = truncate(content, 200)

    lines.append(f"{source_tag} {ref}")
    lines.append(f"  {content}")

    if verbose and result.metadata:
        meta_parts = [f"{k}={v}" for k, v in result.metadata.items() if v]
        if meta_parts:
            lines.append(f"  ({', '.join(meta_parts)})")

    return "\n".join(lines)


@space_cmd("search")
def main() -> None:
    parser = argparse.ArgumentParser(description="search primitives")
    parser.add_argument("query", help="query to search")
    parser.add_argument(
        "--scope", default="all", help="scope: spawns|messages|insights|decisions|tasks|all"
    )
    parser.add_argument("--after", help="filter after date (ISO format)")
    parser.add_argument("--before", help="filter before date (ISO format)")
    parser.add_argument("--recent", type=int, help="filter to last N days")
    parser.add_argument("-n", "--limit", type=int, default=20, help="max results")
    parser.add_argument("-v", "--verbose", action="store_true", help="show metadata")
    parser.add_argument("-j", "--json", action="store_true", help="JSON output")
    parser.add_argument("-p", "--project", help="project name")
    parser.add_argument(
        "-g", "--global", dest="all_projects", action="store_true", help="all projects"
    )
    args = parser.parse_args()

    valid_scopes = ("all", *SOURCES)
    if args.scope not in valid_scopes:
        fail(f"Error: Invalid scope '{args.scope}'. Use: {', '.join(valid_scopes)}")

    if args.recent and args.after:
        fail("Error: Cannot use both --recent and --after")

    project = None
    if args.project:
        try:
            project_id = projects.get_scope(args.project)
            project = projects.get(ProjectId(project_id))
        except NotFoundError:
            pass

    after_iso = (
        _recent_to_after(args.recent)
        if args.recent
        else (_parse_date(args.after) if args.after else None)
    )
    before_iso = _parse_date(args.before) if args.before else None

    results = query(
        args.query,
        scope=args.scope,
        after=after_iso,
        before=before_iso,
        limit=args.limit,
        project_id=project.id if project else None,
    )

    if args.json:
        data = [
            {
                "source": r.source,
                "content": r.content,
                "reference": r.reference,
                "timestamp": r.timestamp,
                "weight": r.weight,
                "metadata": r.metadata,
            }
            for r in results
        ]
        echo(json.dumps({"query": args.query, "scope": args.scope, "results": data}, indent=2))
        return

    if not results:
        echo(f"No results for '{args.query}'")
        return

    echo(f"Found {len(results)} results:\n")
    for result in results:
        echo(_format_result(result, args.verbose))
        echo()
