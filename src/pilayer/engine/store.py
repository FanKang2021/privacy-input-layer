"""本地 sqlite 映射存储：占位符 <-> DPAPI 密文，全部留在本机。

original 列以 Windows DPAPI（当前用户密钥）加密存储，满足 PCI DSS 3.4 /
OWASP ASVS V8 静态不可读要求；去重靠 sha256 哈希列，不解密全表。
"""

import ctypes
import hashlib
import re
import sqlite3
import threading
import time
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\[(PHONE|IDCARD|BANKCARD|EMAIL|KEYWORD|PRIVKEY|IP|TOKEN|SECRET|URL|ENTROPY)_\d+\]")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    fn = _crypt32.CryptProtectData if encrypt else _crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError(f"DPAPI error {ctypes.GetLastError()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def _hash(original: str) -> str:
    return hashlib.sha256(original.encode("utf-8")).hexdigest()


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
                original BLOB NOT NULL,
                original_hash TEXT,
                created_at REAL NOT NULL,
                last_used REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS counters(kind TEXT PRIMARY KEY, value INTEGER NOT NULL);
            """
        )
        self._migrate()
        self._db.commit()

    def _migrate(self):
        cols = [r[1] for r in self._db.execute("PRAGMA table_info(mappings)")]
        if "original_hash" not in cols:
            self._db.execute("ALTER TABLE mappings ADD COLUMN original_hash TEXT")
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_original ON mappings(kind, original_hash)"
        )
        for ph, kind, original in self._db.execute(
            "SELECT placeholder, kind, original FROM mappings WHERE original_hash IS NULL"
        ).fetchall():
            plain = original if isinstance(original, str) else _dpapi(original, False).decode("utf-8")
            self._db.execute(
                "UPDATE mappings SET original=?, original_hash=? WHERE placeholder=?",
                (_dpapi(plain.encode("utf-8"), True), _hash(plain), ph),
            )

    def get_or_create(self, kind: str, original: str) -> str:
        """同一原文复用同一占位符，保证多轮对话中占位符稳定。"""
        now = time.time()
        h = _hash(original)
        with self._lock:
            row = self._db.execute(
                "SELECT placeholder FROM mappings WHERE kind=? AND original_hash=? "
                "ORDER BY created_at DESC LIMIT 1",
                (kind, h),
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
                "INSERT INTO mappings(placeholder, kind, original, original_hash, created_at, last_used) "
                "VALUES (?,?,?,?,?,?)",
                (placeholder, kind, _dpapi(original.encode("utf-8"), True), h, now, now),
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
        if row is None:
            return None
        return _dpapi(row[0], False).decode("utf-8")

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

    def purge_expired(self, ttl_days: int) -> int:
        cutoff = time.time() - ttl_days * 86400
        with self._lock:
            cur = self._db.execute("DELETE FROM mappings WHERE created_at < ?", (cutoff,))
            self._db.commit()
            return cur.rowcount

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