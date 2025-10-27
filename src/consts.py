from typing import Final, List

API_BASE_URL: Final[str] = "https://internal.qudata.ai/v0"
APP_HEADER_NAME: Final[str] = "X-Agent-Secret"

KATAGUARD_SOCK_PATH: Final[str] = "/run/kataguard/agent.sock"
DOCKER_FORBIDDEN_CMDS: Final[List[str]] = [
    "/exec",
    "/attach",
    "/cp",
    "/copy",
    "/commit",
    "/rename",
]

INSTALL_REPORT_PATH: Final[str] = "/var/log/kataguard/agent/report.json"
