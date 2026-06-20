import sqlite3
import time
import uuid
from typing import Any, Dict, Optional

from config import DB_PATH, TTL_SECONDS
from pin_utils import hash_pin, verify_pin

_pending_attempts: Dict[str, int] = {}
_pending_decrypt: Dict[int, str] = {}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                key TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                pin_salt TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                sd_delay INTEGER,
                inline_message_id TEXT,
                chat_id INTEGER,
                message_id INTEGER,
                created_at REAL NOT NULL
            )
            """
        )
        conn.commit()


def _cleanup(conn: sqlite3.Connection) -> None:
    cutoff = time.time() - TTL_SECONDS
    conn.execute("DELETE FROM secrets WHERE created_at < ?", (cutoff,))


def store_secret(text: str, pin: str) -> str:
    init_db()
    key = uuid.uuid4().hex[:12]
    salt_hex, hash_hex = hash_pin(pin)
    with _connect() as conn:
        _cleanup(conn)
        conn.execute(
            """
            INSERT INTO secrets (key, text, pin_salt, pin_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key, text, salt_hex, hash_hex, time.time()),
        )
        conn.commit()
    return key


def get_secret(key: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        _cleanup(conn)
        row = conn.execute("SELECT * FROM secrets WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    return dict(row)


def check_pin(key: str, pin: str) -> Optional[str]:
    secret = get_secret(key)
    if not secret:
        return None
    if verify_pin(pin, secret["pin_salt"], secret["pin_hash"]):
        _pending_attempts.pop(key, None)
        return secret["text"]
    attempts = _pending_attempts.get(key, 0) + 1
    _pending_attempts[key] = attempts
    return None


def pin_attempts(key: str) -> int:
    return _pending_attempts.get(key, 0)


def set_pending_decrypt(user_id: int, key: Optional[str]) -> None:
    if key:
        _pending_decrypt[user_id] = key
    else:
        _pending_decrypt.pop(user_id, None)


def get_pending_decrypt(user_id: int) -> Optional[str]:
    return _pending_decrypt.get(user_id)


def arm_self_destruct(
    key: str,
    delay: int,
    *,
    inline_message_id: Optional[str] = None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
) -> bool:
    init_db()
    with _connect() as conn:
        _cleanup(conn)
        cur = conn.execute(
            """
            UPDATE secrets
            SET sd_delay = ?, inline_message_id = ?, chat_id = ?, message_id = ?, created_at = ?
            WHERE key = ?
            """,
            (delay, inline_message_id, chat_id, message_id, time.time(), key),
        )
        conn.commit()
        return cur.rowcount > 0


def pop_self_destruct_target(key: str) -> Optional[Dict[str, Any]]:
    secret = get_secret(key)
    if not secret or not secret.get("sd_delay"):
        return None

    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE secrets
            SET sd_delay = NULL, inline_message_id = NULL, chat_id = NULL, message_id = NULL
            WHERE key = ?
            """,
            (key,),
        )
        conn.commit()

    return {
        "delay": secret["sd_delay"],
        "inline_message_id": secret.get("inline_message_id"),
        "chat_id": secret.get("chat_id"),
        "message_id": secret.get("message_id"),
    }
