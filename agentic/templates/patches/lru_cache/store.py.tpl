import sqlite3
import threading
from collections import OrderedDict


class Store:
    def __init__(self, path=":memory:", cache_size=1024):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS links (code TEXT PRIMARY KEY, url TEXT NOT NULL)")
        self.conn.commit()
        self.cache_size = cache_size
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self.db_reads = 0  # observable so tests can prove the cache works

    def save(self, code, url):
        self.conn.execute("INSERT OR REPLACE INTO links (code, url) VALUES (?, ?)", (code, url))
        self.conn.commit()
        with self._lock:
            self._cache.pop(code, None)  # invalidate: never serve a stale mapping

    def get(self, code):
        with self._lock:
            if code in self._cache:
                self._cache.move_to_end(code)
                return self._cache[code]
        row = self.conn.execute("SELECT url FROM links WHERE code = ?", (code,)).fetchone()
        self.db_reads += 1
        url = row[0] if row else None
        if url is not None:
            with self._lock:
                self._cache[code] = url
                self._cache.move_to_end(code)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return url
