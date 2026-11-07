"""Local database regression tests. Run: backend/.venv/Scripts/python -m unittest discover -s tests -p test_sqlite.py"""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


class SQLiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "nested" / "chat.db"
        with patch.dict(os.environ, DATABASE_URL="sqlite:///" + path.as_posix()):
            spec = importlib.util.spec_from_file_location("local_db", Path(__file__).resolve().parents[1] / "backend/app/db.py")
            self.db = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.db)
        self.db.init_db()

    def user(self, c, email="alice@example.com"):
        return c.execute("INSERT INTO users(name,email,password_hash,preferred_language) VALUES(?,?,?,?) RETURNING id",
                         ("Alice", email, "hash", "eng_Latn")).fetchone()["id"]

    def test_generated_ids_timestamp_and_persistence(self):
        with self.db.connect() as c:
            uid = self.user(c)
        self.db.init_db()  # Safe to restart without losing accounts.
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            self.assertEqual(row["email"], "alice@example.com")
            self.assertTrue(row["created_at"])
            self.assertEqual(c.execute("SELECT * FROM users WHERE LOWER(name) LIKE LOWER(?)", ("%ALIC%",)).fetchone()["id"], uid)

    def test_duplicate_registration_and_rollback(self):
        with self.assertRaises(self.db.INTEGRITY_ERRORS):
            with self.db.connect() as c:
                self.user(c)
                self.user(c)
        with self.db.connect() as c:
            self.assertIsNone(c.execute("SELECT * FROM users").fetchone())

    def test_foreign_keys(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.connect() as c:
                c.execute("INSERT INTO messages(sender_id,recipient_id,original_text,original_language) VALUES(1,2,'Hello','eng_Latn')")

    def test_message_translation_upsert_and_delete(self):
        with self.db.connect() as c:
            sender = self.user(c)
            recipient = self.user(c, "bob@example.com")
            mid = c.execute("INSERT INTO messages(sender_id,recipient_id,original_text,original_language) VALUES(?,?,?,?) RETURNING id",
                            (sender, recipient, "Hello", "eng_Latn")).fetchone()["id"]
            for text in ("Old translation", "New translation"):
                c.execute("INSERT INTO message_translations(message_id,user_id,language,translated_text) VALUES(?,?,?,?) ON CONFLICT(message_id,user_id) DO UPDATE SET language=excluded.language,translated_text=excluded.translated_text",
                          (mid, recipient, "zul_Latn", text))
            self.assertEqual(c.execute("SELECT translated_text FROM message_translations WHERE message_id=?", (mid,)).fetchone()["translated_text"], "New translation")
            c.execute("DELETE FROM message_translations WHERE message_id=?", (mid,))
            c.execute("DELETE FROM messages WHERE id=?", (mid,))
            self.assertIsNone(c.execute("SELECT * FROM messages").fetchone())


if __name__ == "__main__":
    unittest.main()
