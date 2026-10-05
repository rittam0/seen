import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from filelock import FileLock

DEFAULTS = {"paused": True, "excluded_apps": ["1password.exe", "keepass.exe", "bitwarden.exe", "codex.exe"], "generation": 0}


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "screenshots").mkdir(exist_ok=True)
        self.lock = FileLock(str(self.root / "history.lock"), timeout=60)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS events (
              event_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
              application TEXT NOT NULL, window_title TEXT NOT NULL,
              screenshot_path TEXT NOT NULL, extracted_text TEXT NOT NULL,
              text_embedding BLOB, image_embedding BLOB, indexing_ms REAL NOT NULL,
              ocr_status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_time ON events(timestamp);
            CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
              application, window_title, extracted_text, content='events', content_rowid='event_id', tokenize='porter unicode61');
            CREATE TRIGGER IF NOT EXISTS event_insert AFTER INSERT ON events BEGIN
              INSERT INTO event_fts(rowid, application, window_title, extracted_text)
              VALUES (new.event_id, new.application, new.window_title, new.extracted_text);
            END;
            CREATE TRIGGER IF NOT EXISTS event_delete AFTER DELETE ON events BEGIN
              INSERT INTO event_fts(event_fts,rowid,application,window_title,extracted_text)
              VALUES ('delete',old.event_id,old.application,old.window_title,old.extracted_text);
            END;
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            for key, value in DEFAULTS.items():
                db.execute("INSERT OR IGNORE INTO state VALUES (?,?)", (key, json.dumps(value)))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "seen.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.connect() as db:
            return {row['key']: json.loads(row['value']) for row in db.execute("SELECT * FROM state")}

    def set_state(self, **values):
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO state VALUES (?,?)", [(k, json.dumps(v)) for k, v in values.items()])

    def controls(self, **values):
        with self.lock:
            values['generation'] = self.settings()['generation'] + 1
            self.set_state(**values)
        return self.settings()

    def add(self, timestamp, application, window_title, screenshot_path, extracted_text,
            text_embedding=None, indexing_ms=0, ocr_status="provided"):
        with self.connect() as db:
            cur = db.execute('''INSERT INTO events(timestamp,application,window_title,screenshot_path,
                extracted_text,text_embedding,indexing_ms,ocr_status) VALUES (?,?,?,?,?,?,?,?)''',
                (timestamp, application, window_title, screenshot_path, extracted_text,
                 text_embedding, indexing_ms, ocr_status))
            return cur.lastrowid

    def get(self, event_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            return public(row) if row else None

    def history(self, limit=30, offset=0, bounds=None):
        where, args = ("WHERE timestamp>=? AND timestamp<?", list(bounds)) if bounds else ("", [])
        with self.connect() as db:
            return [public(r) for r in db.execute(f"SELECT * FROM events {where} ORDER BY timestamp DESC,event_id DESC LIMIT ? OFFSET ?", args + [limit, offset])]

    def stats(self):
        with self.connect() as db:
            row = dict(db.execute("SELECT COUNT(*) AS events, COUNT(text_embedding) AS embedded_events, COALESCE(SUM(indexing_ms),0) AS indexing_ms FROM events").fetchone())
        row['disk_bytes'] = 0
        row['model_bytes'] = 0
        for p in self.root.rglob('*'):
            try:
                if p.is_file():
                    size = p.stat().st_size
                    row['disk_bytes'] += size
                    if 'models' in p.relative_to(self.root).parts:
                        row['model_bytes'] += size
            except FileNotFoundError:
                pass  # Another process may be finishing a checkpoint or deletion.
        row['history_bytes'] = row['disk_bytes'] - row['model_bytes']
        return row

    def delete(self):
        with self.lock:
            self.controls(paused=True)
            with self.connect() as db:
                db.execute("DELETE FROM events")
                db.execute("INSERT INTO event_fts(event_fts) VALUES('rebuild')")
            for path in (self.root / 'screenshots').iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
            (self.root / 'vectors.faiss').unlink(missing_ok=True)
            (self.root / 'vectors.tmp').unlink(missing_ok=True)
            with self.connect() as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.execute("VACUUM")


def public(row):
    item = dict(row)
    item['has_embedding'] = item.pop('text_embedding') is not None
    item.pop('image_embedding', None)
    item['image_url'] = f"/api/events/{item['event_id']}/image"
    item['thumbnail_url'] = f"/api/events/{item['event_id']}/thumbnail"
    return item
