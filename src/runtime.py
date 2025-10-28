import os
import socket
import uuid
from functools import lru_cache

import httpx

from src.utils.ports import get_free_port


@lru_cache
def agent_port() -> int:
    return get_free_port()


@lru_cache
def agent_address() -> str:
    """
    Получает публичный IP адрес сервера.
    Пробует несколько сервисов для надёжности.
    """
    # Список сервисов для получения публичного IP (в порядке приоритета)
    ip_services = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
        "https://checkip.amazonaws.com",
        "https://ipinfo.io/ip",
    ]
    
    print("Getting public IP address...")
    
    for service in ip_services:
        try:
            print(f"  Trying {service}...")
            response = httpx.get(service, timeout=5.0, follow_redirects=True)
            if response.status_code == 200:
                ip = response.text.strip()
                # Простая валидация IP адреса
                parts = ip.split('.')
                if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                    print(f"  ✓ Got public IP: {ip}")
                    return ip
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            continue
    
    # Если все сервисы недоступны, пробуем получить локальный IP
    print("  ⚠ All IP services failed, trying local IP...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        print(f"  ⚠ Using local IP: {ip}")
        return ip
    except Exception:
        print("  ✗ Could not determine IP, using 127.0.0.1")
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
