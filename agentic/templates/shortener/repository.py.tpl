"""Persistence. All SQL is parameterised; the service only sees this small interface."""
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code        TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clicks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT NOT NULL,
    ts        TEXT NOT NULL,
    referrer  TEXT
);
CREATE INDEX IF NOT EXISTS idx_clicks_code_ts ON clicks (code, ts);
"""


class SqliteRepository:
    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def create_link(self, code: str, url: str, created_at: str) -> bool:
        """Insert a link. Returns False if the code already exists (unique constraint)."""
        with self._lock:
            try:
                self._conn.execute("INSERT INTO links (code, url, created_at) VALUES (?, ?, ?)",
                                   (code, url, created_at))
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                self._conn.rollback()
                return False

    def get_url(self, code: str):
        with self._lock:
            row = self._conn.execute("SELECT url FROM links WHERE code = ?", (code,)).fetchone()
        return row[0] if row else None

    def record_click(self, code: str, ts: str, referrer) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO clicks (code, ts, referrer) VALUES (?, ?, ?)", (code, ts, referrer))
            self._conn.commit()

    def stats(self, code: str) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM clicks WHERE code = ?", (code,)).fetchone()[0]
            by_day = self._conn.execute(
                "SELECT substr(ts, 1, 10) AS day, COUNT(*) FROM clicks WHERE code = ? GROUP BY day ORDER BY day",
                (code,)).fetchall()
            refs = self._conn.execute(
                "SELECT COALESCE(referrer, '(direct)') AS ref, COUNT(*) AS n FROM clicks WHERE code = ? "
                "GROUP BY ref ORDER BY n DESC, ref LIMIT 5", (code,)).fetchall()
        return {
            "total_clicks": total,
            "clicks_by_day": [{"date": d, "count": n} for d, n in by_day],
            "top_referrers": [{"referrer": r, "count": n} for r, n in refs],
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
