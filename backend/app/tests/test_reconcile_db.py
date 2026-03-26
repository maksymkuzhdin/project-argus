from scripts.reconcile_db import HEAD_REVISION, reconcile


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        if "SELECT version_num FROM alembic_version" in sql:
            return _FakeResult(self.row)
        return _FakeResult(None)


class _FakeBeginContext:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def begin(self):
        return _FakeBeginContext(self._conn)


def _was_executed(conn: _FakeConn, needle: str) -> bool:
    return any(needle in sql for sql, _ in conn.calls)


def _executed_with_param(conn: _FakeConn, needle: str, expected: dict) -> bool:
    return any((needle in sql and params == expected) for sql, params in conn.calls)


def test_reconcile_initializes_version_when_missing():
    conn = _FakeConn(row=None)
    reconcile(_FakeEngine(conn))

    assert _was_executed(conn, "CREATE TABLE IF NOT EXISTS alembic_version")
    assert _executed_with_param(
        conn,
        "INSERT INTO alembic_version",
        {"v": HEAD_REVISION},
    )


def test_reconcile_updates_unknown_revision():
    conn = _FakeConn(row=("legacy_unknown_rev",))
    reconcile(_FakeEngine(conn))

    assert _executed_with_param(
        conn,
        "UPDATE alembic_version SET version_num = :v",
        {"v": HEAD_REVISION},
    )


def test_reconcile_keeps_known_revision():
    conn = _FakeConn(row=(HEAD_REVISION,))
    reconcile(_FakeEngine(conn))

    assert not _was_executed(conn, "UPDATE alembic_version SET version_num")
    assert not _was_executed(conn, "INSERT INTO alembic_version")
