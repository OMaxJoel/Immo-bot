import json
import os
import sqlite3
import time


class DB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.c = sqlite3.connect(path)
        self.c.row_factory = sqlite3.Row
        self.c.executescript("""
        CREATE TABLE IF NOT EXISTS seen(url TEXT PRIMARY KEY, ts REAL);
        CREATE TABLE IF NOT EXISTS ads(fp TEXT PRIMARY KEY, url TEXT, data TEXT,
                                       relevance INT, ts REAL, sent INT DEFAULT 0);
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
        """)
        self.c.commit()

    # --- annonces déjà examinées (par URL) ---
    def is_seen(self, url):
        return self.c.execute("SELECT 1 FROM seen WHERE url=?", (url,)).fetchone() is not None

    def mark_seen(self, url):
        self.c.execute("INSERT OR IGNORE INTO seen VALUES(?,?)", (url, time.time()))
        self.c.commit()

    # --- annonces retenues (dédoublonnage par empreinte) ---
    def has_fp(self, fp):
        return self.c.execute("SELECT 1 FROM ads WHERE fp=?", (fp,)).fetchone() is not None

    def add_ad(self, fp, url, data: dict, relevance: int, sent: bool):
        self.c.execute("INSERT OR IGNORE INTO ads VALUES(?,?,?,?,?,?)",
                       (fp, url, json.dumps(data, ensure_ascii=False), relevance, time.time(), int(sent)))
        self.c.commit()

    def recent(self, n=10, since=None):
        q = "SELECT * FROM ads WHERE ts>=? ORDER BY ts DESC LIMIT ?"
        rows = self.c.execute(q, (since or 0, n)).fetchall()
        return [dict(json.loads(r["data"]), url=r["url"], relevance=r["relevance"], ts=r["ts"]) for r in rows]

    # --- paramètres ---
    def get(self, k, default=None):
        r = self.c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set(self, k, v):
        self.c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, v))
        self.c.commit()
