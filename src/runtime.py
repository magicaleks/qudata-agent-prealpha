import os
import socket
import uuid
from functools import lru_cache

from src.utils.ports import get_free_port


@lru_cache
def agent_port() -> int:
    return get_free_port()


@lru_cache
def agent_address() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@lru_cache
def agent_pid() -> int:
    try:
        return os.getpid()
    except Exception:
        return -1

@lru_cache
def agent_id() -> str:
    return uuid.uuid4().hex
