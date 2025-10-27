from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List


@dataclass
class CreateInstance:
    image: str
    image_tag: str
    storage_gb: int

    registry: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None

    env_variables: Dict[str, str] = field(default_factory=dict)
    ports: Dict[str, str] = field(default_factory=dict)

    command: Optional[str] = None
    ssh_enabled: bool = False


@dataclass
class InstanceCreated:
    success: bool
    ports: List[str] = field(default_factory=list)
    tunnel_host: Optional[str] = None
    tunnel_token: Optional[str] = None


class InstanceAction(Enum):
    start = "start"
    stop = "stop"
    restart = "restart"
    delete = "delete"


@dataclass
class ManageInstance:
    action: str
