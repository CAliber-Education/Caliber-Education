"""A minimal in-memory stand-in for the supabase-py Client, covering only the
.table(...).select/eq/ilike/in_/order/single/limit/insert/upsert/update/delete/execute()
chains actually used by app/routers/mcq.py and app/routers/admin.py.

This exists so MCQ integrity tests never touch the real Supabase database —
there is no separate test/staging project, and production data must not be
read from or written to by an automated test run.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable


class FakeResult:
    def __init__(self, data: Any, count: int | None = None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, store: dict[str, list[dict]], table_name: str):
        self._store = store
        self._table = table_name
        self._filters: list[Callable[[dict], bool]] = []
        self._order: tuple[str, bool] | None = None
        self._single = False
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None
        self._count_mode: str | None = None
        self._pending_insert: list[dict] | None = None
        self._pending_upsert_ids: set | None = None
        self._conflict_col: str = "id"
        self._pending_delete = False
        self._pending_update: dict | None = None

    # ── filtering ────────────────────────────────────────────────────────
    def select(self, _cols: str = "*", count: str | None = None):
        self._count_mode = count
        return self

    def eq(self, col: str, val: Any):
        self._filters.append(lambda row, col=col, val=val: row.get(col) == val)
        return self

    def ilike(self, col: str, val: Any):
        needle = str(val).lower()
        self._filters.append(lambda row, col=col, needle=needle: str(row.get(col, "")).lower() == needle)
        return self

    def in_(self, col: str, vals: Any):
        valset = set(vals)
        self._filters.append(lambda row, col=col, valset=valset: row.get(col) in valset)
        return self

    def or_(self, *_args, **_kwargs):
        # Not modeled: only used for the best-effort rank/percentile lookup,
        # which none of the MCQ-integrity tests assert on. Left as a no-op
        # passthrough rather than raising, so it behaves like "no extra
        # attempts beat this one" against an empty quiz_attempts table.
        return self

    def order(self, col: str, desc: bool = False):
        self._order = (col, desc)
        return self

    def single(self):
        self._single = True
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def range(self, start: int, end: int):
        # PostgREST ranges are inclusive at both ends.
        self._range = (start, end)
        return self

    # ── mutations ────────────────────────────────────────────────────────
    def insert(self, row_or_rows: Any):
        self._pending_insert = row_or_rows if isinstance(row_or_rows, list) else [row_or_rows]
        return self

    def upsert(self, row_or_rows: Any, on_conflict: str | None = None, **_kwargs):
        # Defaults to "id" (matching most upsert call sites in this
        # codebase), but respects on_conflict when the real unique
        # constraint is a different column (e.g. mentor_permissions.mentor_id).
        rows = row_or_rows if isinstance(row_or_rows, list) else [row_or_rows]
        self._pending_insert = rows
        conflict_col = on_conflict or "id"
        self._conflict_col = conflict_col
        self._pending_upsert_ids = {r.get(conflict_col) for r in rows}
        return self

    def delete(self):
        self._pending_delete = True
        return self

    def update(self, payload: dict):
        self._pending_update = payload
        return self

    # ── terminal ─────────────────────────────────────────────────────────
    def execute(self) -> FakeResult:
        table = self._store.setdefault(self._table, [])

        if self._pending_insert is not None:
            # Real Postgres/Supabase auto-generates `id` via a column
            # default (gen_random_uuid()) when an insert doesn't provide
            # one — mirror that here, since app code that inserts without
            # an explicit id (e.g. mcq_enrollments) relies on being able to
            # look the row back up by its other columns afterward.
            inserted = [
                {"id": r.get("id") or uuid.uuid4().hex, **{k: v for k, v in r.items() if k != "id"}}
                for r in self._pending_insert
            ]
            if self._pending_upsert_ids is not None:
                table[:] = [r for r in table if r.get(self._conflict_col) not in self._pending_upsert_ids]
            table.extend(inserted)
            return FakeResult(inserted)

        if self._pending_delete:
            keep = [r for r in table if not all(f(r) for f in self._filters)]
            table[:] = keep
            return FakeResult([])

        if self._pending_update is not None:
            # Mirrors supabase-py's default return=representation behavior:
            # only rows matching every accumulated filter get mutated, and
            # exactly those (post-mutation) rows come back in `.data` — an
            # empty `.data` means the filters (e.g. a status compare-and-swap
            # guard) matched nothing, which callers rely on to detect a lost
            # race rather than a genuine "no such row".
            matched = [r for r in table if all(f(r) for f in self._filters)]
            for row in matched:
                row.update(self._pending_update)
            return FakeResult(matched)

        rows = [r for r in table if all(f(r) for f in self._filters)]

        if self._order:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)

        count = len(rows) if self._count_mode == "exact" else None

        if self._range is not None:
            rows = rows[self._range[0]: self._range[1] + 1]
        if self._limit is not None:
            rows = rows[: self._limit]

        if self._single:
            return FakeResult(rows[0] if rows else None, count)
        return FakeResult(rows, count)


class FakeSupabaseClient:
    """Drop-in replacement for `Client` in dependency_overrides[get_db]."""

    def __init__(self):
        self.store: dict[str, list[dict]] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self.store, name)

    def seed(self, table_name: str, rows: list[dict]):
        self.store.setdefault(table_name, []).extend(dict(r) for r in rows)
