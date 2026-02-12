from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, TypeVar

from space.lib.store.connection import DataclassInstance, from_row

T = TypeVar("T", bound=DataclassInstance)


@dataclass(slots=True)
class Query:
    _table: str
    _select: str = "*"
    _conditions: list[str] | None = None
    _params: list[Any] | None = None
    _order: str | None = None
    _limit: int | None = None
    _joins: list[str] | None = None

    def select(self, cols: str) -> Query:
        return Query(
            self._table,
            cols,
            self._conditions,
            self._params,
            self._order,
            self._limit,
            self._joins,
        )

    def where(self, condition: str, *params: Any) -> Query:
        conditions = list(self._conditions or [])
        conditions.append(condition)
        all_params = list(self._params or [])
        all_params.extend(params)
        return Query(
            self._table,
            self._select,
            conditions,
            all_params,
            self._order,
            self._limit,
            self._joins,
        )

    def where_if(self, condition: str, value: Any) -> Query:
        if value is None:
            return self
        return self.where(condition, value)

    def where_in(self, column: str, values: list[Any]) -> Query:
        if not values:
            return self.where("1 = 0")
        placeholders = ",".join("?" * len(values))
        return self.where(f"{column} IN ({placeholders})", *values)

    def join(self, join_clause: str) -> Query:
        joins = list(self._joins or [])
        joins.append(join_clause)
        return Query(
            self._table,
            self._select,
            self._conditions,
            self._params,
            self._order,
            self._limit,
            joins,
        )

    def order(self, clause: str) -> Query:
        return Query(
            self._table,
            self._select,
            self._conditions,
            self._params,
            clause,
            self._limit,
            self._joins,
        )

    def limit(self, n: int | None) -> Query:
        return Query(
            self._table,
            self._select,
            self._conditions,
            self._params,
            self._order,
            n,
            self._joins,
        )

    def not_deleted(self) -> Query:
        return self.where("deleted_at IS NULL")

    def not_archived(self) -> Query:
        return self.where("archived_at IS NULL")

    def active(self) -> Query:
        return self.not_deleted().not_archived()

    def build(self) -> tuple[str, list[Any]]:
        parts = [f"SELECT {self._select} FROM {self._table}"]  # noqa: S608
        if self._joins:
            parts.extend(self._joins)
        if self._conditions:
            parts.append("WHERE " + " AND ".join(self._conditions))
        if self._order:
            parts.append(f"ORDER BY {self._order}")
        if self._limit:
            parts.append(f"LIMIT {self._limit}")
        return " ".join(parts), list(self._params or [])

    def execute(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        sql, params = self.build()
        return conn.execute(sql, params).fetchall()

    def fetch(self, conn: sqlite3.Connection, cls: type[T]) -> list[T]:
        return [from_row(row, cls) for row in self.execute(conn)]

    def fetch_one(self, conn: sqlite3.Connection, cls: type[T]) -> T | None:
        rows = self.limit(1).execute(conn)
        return from_row(rows[0], cls) if rows else None

    def count(self, conn: sqlite3.Connection) -> int:
        q = Query(
            self._table,
            "COUNT(*)",
            self._conditions,
            self._params,
            None,
            None,
            self._joins,
        )
        sql, params = q.build()
        return conn.execute(sql, params).fetchone()[0]


def q(table: str) -> Query:
    return Query(table)
