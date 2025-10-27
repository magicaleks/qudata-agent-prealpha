import hashlib
from functools import lru_cache
from typing import Optional

from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def _get_machine_id() -> Optional[str]:
    success, stdout, _ = run_command(["cat", "/etc/machine-id"])
    if success and stdout:
        return stdout.strip()

    success, stdout, _ = run_command(["cat", "/var/lib/dbus/machine-id"])
    if success and stdout:
        return stdout.strip()

    success, stdout, _ = run_command(["dmidecode", "-s", "baseboard-serial-number"])
    if success and stdout and "serial" in stdout.lower():
        return stdout.strip()

    return None


@lru_cache
def get_fingerprint() -> str:
    print("Generating fingerprint...")
    machine_id = _get_machine_id()

    if not machine_id:
        print("Failed to retrieve machine ID, using hostname")
        import socket

        try:
            machine_id = socket.gethostname()
        except Exception:
            machine_id = "unknown-host"

    fingerprint = hashlib.sha256(machine_id.encode("utf-8")).hexdigest()
    print(f"Fingerprint generated: {fingerprint[:12]}...")
    return fingerprint
