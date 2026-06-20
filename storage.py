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
    _pending[key] = {"text": text, "ts": time.time(), "sd_delay": None}
    return key


def get_text(key: str) -> Optional[str]:
    _cleanup()
    data = _pending.get(key)
    return data["text"] if data else None


def arm_self_destruct(key: str, delay: int) -> bool:
    _cleanup()
    data = _pending.get(key)
    if not data:
        return False
    data["sd_delay"] = delay
    data["ts"] = time.time()
    return True


def pop_self_destruct_delay(key: str) -> Optional[int]:
    _cleanup()
    data = _pending.get(key)
    if not data:
        return None
    delay = data.get("sd_delay")
    data["sd_delay"] = None
    return delay
