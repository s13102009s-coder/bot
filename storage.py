import time
import uuid
from typing import Optional

from config import TTL_SECONDS

_pending = {}


def _cleanup():
    now = time.time()
    expired = [key for key, data in _pending.items() if now - data["ts"] > TTL_SECONDS]
    for key in expired:
        del _pending[key]


def store_text(text: str) -> str:
    _cleanup()
    key = uuid.uuid4().hex[:12]
    _pending[key] = {"text": text, "ts": time.time()}
    return key


def get_text(key: str) -> Optional[str]:
    _cleanup()
    data = _pending.get(key)
    return data["text"] if data else None
