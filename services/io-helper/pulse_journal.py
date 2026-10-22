"""One durable monotonic NV9 stream. A pulse is published only after commit."""
import sqlite3
import json
import threading
from pathlib import Path
from uuid import uuid4

class PulseJournal:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock()
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS counter(id INTEGER PRIMARY KEY CHECK(id=1),stream TEXT NOT NULL,total INTEGER NOT NULL CHECK(total>=0))')
        self.conn.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.conn.execute('INSERT OR IGNORE INTO counter VALUES(1,?,0)',(uuid4().hex,))
        self.conn.commit()
        row=self.conn.execute('SELECT stream,total FROM counter WHERE id=1').fetchone()
        if row is None:raise RuntimeError('NV9 journal is invalid')
        self.stream_id,self.total=row
    def increment(self):
        with self.lock:
            try:
                self.conn.execute('UPDATE counter SET total=total+1 WHERE id=1')
                self.conn.commit()
            except BaseException:
                self.conn.rollback();raise
            self.total=self.conn.execute('SELECT total FROM counter WHERE id=1').fetchone()[0]
            return self.total
    def value(self):
        with self.lock:return self.total
    def close(self):
        with self.lock:self.conn.close()

    def get_setting(self,key,default=None):
        with self.lock:
            row=self.conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        with self.lock:
            try:
                self.conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value,allow_nan=False)))
                self.conn.commit()
            except BaseException:
                self.conn.rollback();raise
