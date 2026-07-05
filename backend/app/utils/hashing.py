"""Content hashing used for duplicate-document detection."""

import hashlib


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
