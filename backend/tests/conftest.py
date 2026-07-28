import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# backend/ is what uvicorn treats as the run-from root (`uvicorn app.main:app`
# from within backend/), so app.* absolute imports resolve the same way here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeQuery:
    """Minimal stand-in for supabase-py's fluent query builder, covering
    exactly the chained calls scoring_service.py/report_service.py use:
    select/eq/lte/in_/order/limit/execute, insert/execute, update/eq/execute."""

    def __init__(self, rows: list, table_name: str):
        self._rows = rows
        self._table_name = table_name
        self._eq: dict = {}
        self._lte: dict = {}
        self._in: dict = {}
        self._order_col = None
        self._order_desc = False
        self._limit = None
        self._op = None
        self._payload = None

    def select(self, _cols="*"):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def lte(self, col, val):
        self._lte[col] = val
        return self

    def in_(self, col, vals):
        self._in[col] = set(vals)
        return self

    def order(self, col, desc=False):
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row: dict) -> bool:
        for k, v in self._eq.items():
            if row.get(k) != v:
                return False
        for k, v in self._lte.items():
            if row.get(k) is None or row[k] > v:
                return False
        for k, v in self._in.items():
            if row.get(k) not in v:
                return False
        return True

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._rows if self._matches(r)]
            if self._order_col:
                rows = sorted(rows, key=lambda r: r[self._order_col], reverse=self._order_desc)
            if self._limit is not None:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)

        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payload:
                row = dict(p)
                row.setdefault("id", f"{self._table_name}-{len(self._rows)}")
                self._rows.append(row)
                inserted.append(row)
            return SimpleNamespace(data=inserted)

        if self._op == "update":
            matched = [r for r in self._rows if self._matches(r)]
            for r in matched:
                r.update(self._payload)
            return SimpleNamespace(data=matched)

        if self._op == "delete":
            matched = [r for r in self._rows if self._matches(r)]
            for r in matched:
                self._rows.remove(r)
            return SimpleNamespace(data=matched)

        raise AssertionError("FakeQuery.execute() called with no operation set")


class FakeSupabase:
    """In-memory stand-in for the supabase-py Client, enough to exercise
    scoring_service.py/report_service.py without any network access."""

    def __init__(self):
        self.store: dict[str, list] = {}

    def table(self, name: str) -> FakeQuery:
        self.store.setdefault(name, [])
        return FakeQuery(self.store[name], name)


@pytest.fixture
def fake_supabase():
    return FakeSupabase()
