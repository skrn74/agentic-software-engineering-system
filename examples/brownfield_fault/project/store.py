import sqlite3


class Store:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS links (code TEXT PRIMARY KEY, url TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, ts TEXT NOT NULL, referrer TEXT)")
        self.conn.commit()

    def save(self, code, url):
        """Legacy behaviour kept for backward compatibility. New code should use save_if_absent."""
        self.conn.execute("INSERT OR REPLACE INTO links (code, url) VALUES (?, ?)", (code, url))
        self.conn.commit()

    def save_if_absent(self, code, url):
        """Atomically store the mapping unless the code is taken by a DIFFERENT url. True when the code now maps to url."""
        self.conn.execute("INSERT OR IGNORE INTO links (code, url) VALUES (?, ?)", (code, url))
        self.conn.commit()
        return self.get(code) == url

    def get(self, code):
        row = self.conn.execute("SELECT url FROM links WHERE code = ?", (code,)).fetchone()
        return row[0] if row else None

    def record_click(self, code, ts, referrer):
        self.conn.execute("INSERT INTO clicks (code, ts, referrer) VALUES (?, ?, ?)", (code, ts, referrer))
        self.conn.commit()

    def stats(self, code):
        total = self.conn.execute("SELECT COUNT(*) FROM clicks WHERE code = ?", (code,)).fetchone()[0]
        by_day = self.conn.execute(
            "SELECT substr(ts, 1, 10) AS day, COUNT(*) FROM clicks WHERE code = ? GROUP BY day ORDER BY day", (code,)).fetchall()
        refs = self.conn.execute(
            "SELECT COALESCE(referrer, '(direct)') AS ref, COUNT(*) AS n FROM clicks WHERE code = ? GROUP BY ref ORDER BY n DESC, ref LIMIT 5",
            (code,)).fetchall()
        return {"code": code, "total_clicks": total,
                "clicks_by_day": [{"date": d, "count": n} for d, n in by_day],
                "top_referrers": [{"referrer": r, "count": n} for r, n in refs]}
