import os
import sqlite3
from pathlib import Path
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://lingualink:lingualink_dev@localhost:5433/lingualink")
SQLITE = DATABASE_URL.startswith("sqlite:///")
if SQLITE:
 SQLITE_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
 SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Keep the API's duplicate-email handling independent of the database driver.
INTEGRITY_ERRORS = (UniqueViolation, sqlite3.IntegrityError)
_pool = None


def pool():
 global _pool
 if _pool is None:
  _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)
  _pool.wait(timeout=30)
 return _pool


def close_pool():
 global _pool
 if _pool is not None:
  _pool.close(); _pool=None


class _Conn:
 """Thin wrapper so queries can keep using '?' placeholders."""
 def __init__(self, c): self.c = c
 def execute(self, sql, params=()): return self.c.execute(sql.replace("?", "%s"), params)


class connect:
 """Open SQLite or borrow PostgreSQL; commit on success, roll back on error."""
 def __enter__(self):
  if SQLITE:
   self.raw = sqlite3.connect(SQLITE_PATH, timeout=30)
   self.raw.row_factory = sqlite3.Row
   self.raw.execute("PRAGMA foreign_keys=ON")
   return self.raw
  self.cm = pool().connection(); self.raw = self.cm.__enter__(); return _Conn(self.raw)
 def __exit__(self, *a):
  if SQLITE:
   try: return self.raw.__exit__(*a)
   finally: self.raw.close()
  return self.cm.__exit__(*a)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,preferred_language TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS messages(id SERIAL PRIMARY KEY,sender_id INTEGER NOT NULL REFERENCES users(id),recipient_id INTEGER NOT NULL REFERENCES users(id),original_text TEXT NOT NULL,original_language TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),attachment_name TEXT,attachment_path TEXT,attachment_mime TEXT);
CREATE TABLE IF NOT EXISTS message_translations(message_id INTEGER NOT NULL REFERENCES messages(id),user_id INTEGER NOT NULL REFERENCES users(id),language TEXT NOT NULL,translated_text TEXT NOT NULL,provider TEXT,PRIMARY KEY(message_id,user_id));
CREATE TABLE IF NOT EXISTS hidden_users(user_id INTEGER NOT NULL,other_id INTEGER NOT NULL,PRIMARY KEY(user_id,other_id));
CREATE TABLE IF NOT EXISTS blocked_users(user_id INTEGER NOT NULL,other_id INTEGER NOT NULL,PRIMARY KEY(user_id,other_id));
CREATE TABLE IF NOT EXISTS chat_clears(user_id INTEGER NOT NULL,other_id INTEGER NOT NULL,cleared_message_id INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,other_id));
CREATE TABLE IF NOT EXISTS message_hidden_for(message_id INTEGER NOT NULL,user_id INTEGER NOT NULL,PRIMARY KEY(message_id,user_id));
CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender_id,recipient_id,id);
"""


def init_db():
 schema = SCHEMA
 if SQLITE:
  schema = schema.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("TIMESTAMPTZ DEFAULT NOW()", "TEXT DEFAULT CURRENT_TIMESTAMP")
 with connect() as c:
  for stmt in schema.split(";"):
   if stmt.strip(): c.execute(stmt)
  if SQLITE:
   columns={row["name"] for row in c.execute("PRAGMA table_info(message_translations)").fetchall()}
   if "provider" not in columns:c.execute("ALTER TABLE message_translations ADD COLUMN provider TEXT")
  else:c.execute("ALTER TABLE message_translations ADD COLUMN IF NOT EXISTS provider TEXT")
