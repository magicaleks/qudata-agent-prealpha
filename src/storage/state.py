import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Dict

from src.utils.xlogging import get_logger

logger = get_logger(__name__)

STATE_FILE_PATH = Path("state.json")


@dataclass
class InstanceState:
    instance_id: Optional[str] = None
    container_id: Optional[str] = None
    status: str = "destroyed"
    luks_device_path: Optional[str] = None
    luks_mapper_name: Optional[str] = None
    allocated_ports: Optional[Dict[str, str]] = None


_current_state: Optional[InstanceState] = None


def get_current_state() -> InstanceState:
    global _current_state
    if _current_state is not None:
        return _current_state

    if not STATE_FILE_PATH.exists():
        _current_state = InstanceState()
        return _current_state

    try:
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            _current_state = InstanceState(**data)
            return _current_state
    except (json.JSONDecodeError, TypeError) as e:
        print(
            f"Failed to load or parse state file {STATE_FILE_PATH}: {e}."
            f" Initializing a fresh state."
        )
        _current_state = InstanceState()
        return _current_state


def save_state(state: InstanceState) -> bool:
    global _current_state
    try:
        STATE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=4)
        _current_state = state
        print(f"State saved successfully. Current status: {state.status}")
        return True
    except (IOError, TypeError) as e:
        print(f"Failed to save state to {STATE_FILE_PATH}: {e}")
        return False


def clear_state() -> bool:
    global _current_state
    if STATE_FILE_PATH.exists():
        try:
            STATE_FILE_PATH.unlink()
        except OSError as e:
            print(f"Failed to delete state file {STATE_FILE_PATH}: {e}")
            return False
    _current_state = InstanceState()
    print("State cleared successfully.")
    return True
