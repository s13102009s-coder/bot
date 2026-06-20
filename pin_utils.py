import hashlib
import os
import re
from typing import Optional, Tuple

from config import PIN_MAX, PIN_MIN

_PIN_RE = re.compile(rf"^(\d{{{PIN_MIN},{PIN_MAX}}})\s+(.+)$", re.DOTALL)


def parse_pin_and_text(raw: str) -> Tuple[Optional[str], str]:
    raw = (raw or "").strip()
    if not raw:
        return None, ""
    match = _PIN_RE.match(raw)
    if not match:
        return None, raw
    return match.group(1), match.group(2).strip()


def hash_pin(pin: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000)
    return salt.hex(), digest.hex()


def verify_pin(pin: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    _, digest = hash_pin(pin, salt)
    return digest == hash_hex
