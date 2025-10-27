import socket
from typing import Tuple


def _port_is_free(port: int) -> bool:
    ip = "0.0.0.0"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((ip, port))
            return True
        except OSError:
            return False


def get_free_port() -> int:
    ip = "0.0.0.0"
    start = 1024
    end = 65535
    for port in range(start, end):
        if _port_is_free(port):
            return port
    raise RuntimeError("Cannot start agent: no ports available")


def _port_seq_is_free(port: int, _range: int) -> bool:
    for p in range(port, port + _range):
        if not _port_is_free(p):
            return False
    return True


def get_ports_range(_range: int) -> Tuple[int, int]:
    start = 1024
    end = 65535 - _range

    for port in range(start, end):
        if _port_seq_is_free(port, _range):
            return port, port + _range - 1

    raise RuntimeError("Cannot range ports: no ports available")
