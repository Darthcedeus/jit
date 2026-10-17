import fcntl
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path, seed):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            exists = db.execute("SELECT name FROM sqlite_master WHERE name='rules'").fetchone()
            db.execute('''CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, port INTEGER NOT NULL,
                proto TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                expires_at REAL, UNIQUE(port, proto))''')
            if not exists:
                for rule in json.loads(Path(seed).read_text()):
                    db.execute('INSERT INTO rules(id,name,port,proto,description) VALUES(:id,:name,:port,:proto,:description)', rule)

    @contextmanager
    def transaction(self):
        # Keep a process-shared lock even if an action commits a write-ahead
        # expiry before touching the kernel. Separate open handles lock threads too.
        with open(self.path + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
                fcntl.flock(lock, fcntl.LOCK_UN)
