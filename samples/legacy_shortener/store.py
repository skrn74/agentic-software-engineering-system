import sqlite3


class Store:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS links (code TEXT PRIMARY KEY, url TEXT NOT NULL)")
        self.conn.commit()

    def save(self, code, url):
        self.conn.execute("INSERT OR REPLACE INTO links (code, url) VALUES (?, ?)", (code, url))
        self.conn.commit()

    def get(self, code):
        row = self.conn.execute("SELECT url FROM links WHERE code = ?", (code,)).fetchone()
        return row[0] if row else None
