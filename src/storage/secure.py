import json
from pathlib import Path
from typing import Optional

SECRET_FILE = Path("secret_key.json")


def get_agent_secret() -> Optional[str]:
    if not SECRET_FILE.exists():
        return None
    try:
        with open(SECRET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("secret_key")
    except Exception:
        return None


def set_agent_secret(secret: str) -> None:
    if not secret:
        return
    try:
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            json.dump({"secret_key": secret}, f)
        SECRET_FILE.chmod(0o600)
    except Exception:
        pass
