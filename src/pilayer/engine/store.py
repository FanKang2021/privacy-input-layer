"""本地 sqlite 映射存储：占位符 <-> 原文，全部留在本机。"""

import re
import sqlite3
import threading
import time
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\[(PHONE|IDCARD|BANKCARD|EMAIL|KEYWORD|PRIVKEY|IP|TOKEN)_\d+\]")


class MappingStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mappings(
                placeholder TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                original TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_used REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_original ON mappings(kind, original);
            CREATE TABLE IF NOT EXISTS counters(kind TEXT PRIMARY KEY, value INTEGER NOT NULL);
            """
        )
        self._db.commit()

    def get_or_create(self, kind: str, original: str) -> str:
        """同一原文复用同一占位符，保证多轮对话中占位符稳定。"""
        now = time.time()
        with self._lock:
            row = self._db.execute(
                "SELECT placeholder FROM mappings WHERE kind=? AND original=? "
                "ORDER BY created_at DESC LIMIT 1",
                (kind, original),
            ).fetchone()
            if row:
                self._db.execute(
                    "UPDATE mappings SET last_used=? WHERE placeholder=?", (now, row[0])
                )
                self._db.commit()
                return row[0]
            n = self._next_counter(kind)
            placeholder = f"[{kind}_{n}]"
            self._db.execute(
                "INSERT INTO mappings VALUES (?,?,?,?,?)",
                (placeholder, kind, original, now, now),
            )
            self._db.commit()
            return placeholder

    def _next_counter(self, kind: str) -> int:
        row = self._db.execute(
            "SELECT value FROM counters WHERE kind=?", (kind,)
        ).fetchone()
        n = (row[0] if row else 0) + 1
        self._db.execute(
            "INSERT INTO counters VALUES (?,?) ON CONFLICT(kind) DO UPDATE SET value=?",
            (kind, n, n),
        )
        return n

    def lookup(self, placeholder: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT original FROM mappings WHERE placeholder=?", (placeholder,)
            ).fetchone()
            return row[0] if row else None

    def restore(self, text: str) -> tuple[str, int, list[str]]:
        """返回 (还原后文本, 成功还原数, 未找到映射的占位符)。"""
        missing: list[str] = []
        count = 0

        def sub(m: re.Match) -> str:
            nonlocal count
            original = self.lookup(m.group())
            if original is None:
                missing.append(m.group())
                return m.group()
            count += 1
            return original

        restored = PLACEHOLDER_RE.sub(sub, text)
        return restored, count, missing

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute(
                "SELECT kind, COUNT(*) FROM mappings GROUP BY kind"
            ).fetchall()
            total = self._db.execute("SELECT COUNT(*) FROM mappings").fetchone()[0]
        return {"total": total, "by_kind": dict(rows)}

    def close(self):
        with self._lock:
            self._db.close()