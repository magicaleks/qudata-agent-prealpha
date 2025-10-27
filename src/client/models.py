from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass
class InitAgent:
    agent_id: str
    agent_port: int
    address: str
    fingerprint: str
    pid: int


@dataclass
class AgentResponse:
    agent_created: bool
    emergency_reinit: bool
    host_exists: bool
    secret_key: Optional[str] = None


@dataclass
class UnitValue:
    amount: float
    unit: str = "gb"


@dataclass
class Location:
    city: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None


@dataclass
class ConfigurationData:
    ram: Optional[UnitValue] = None
    disk: Optional[UnitValue] = None
    cpu_name: Optional[str] = None
    vcpu: Optional[int] = None
    cpu_cores: Optional[int] = None
    cpu_freq: Optional[float] = None
    memory_speed: Optional[float] = None
    ethernet_in: Optional[float] = None
    ethernet_out: Optional[float] = None
    capacity: Optional[float] = None
    max_cuda_version: Optional[float] = None


@dataclass
class CreateHost:
    gpu_name: str
    gpu_amount: int
    vram: float
    location: Location
    configuration: ConfigurationData


class IncidentType(Enum):
    agent_unavailable = "agent_unavailable"
    server_fail = "server_fail"
    privacy_corrupted = "privacy_corrupted"


@dataclass
class Incident:
    incident_type: str
    timestamp: int
    instances_killed: bool


class InstanceStatus(Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    rebooting = "rebooting"
    error = "error"
    destroyed = "destroyed"


@dataclass
class Stats:
    gpu_util: float = 0
    cpu_util: float = 0
    ram_util: float = 0
    mem_util: float = 0
    inet_in: int = 0
    inet_out: int = 0
    status: Optional[str] = None
