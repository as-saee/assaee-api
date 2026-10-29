import os
import time
import uuid


def uuid7() -> str:
    """Time-ordered UUID (RFC 9562 v7): 48-bit millisecond timestamp, then random bits."""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (
        (ms << 80) | (0x7 << 76) | ((rand >> 68) << 64) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    )
    return str(uuid.UUID(int=value))
