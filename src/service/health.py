"""Проверка и восстановление состояния агента"""

from src.service.instances import check_container_exists
from src.storage.state import clear_state, get_current_state, save_state
from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def sync_state_with_docker() -> None:
    """Синхронизирует состояние агента с реальным состоянием Docker"""
    state = get_current_state()
    
    if state.status == "destroyed":
        logger.info("State is clean (destroyed), no sync needed")
        return
    
    if not state.container_id:
        logger.warning("State has no container_id but status is not destroyed, cleaning up")
        clear_state()
        return
    
    # Проверяем существование контейнера
    if not check_container_exists(state.container_id):
        logger.warning(
            f"Container {state.container_id[:12]} in state but not found in Docker, "
            f"state will be cleared"
        )
        clear_state()
        return
    
    # Проверяем статус контейнера в Docker
    success, output, _ = run_command(
        ["docker", "inspect", "--format", "{{.State.Status}}", state.container_id]
    )
    
    if success and output:
        docker_status = output.strip().lower()
        logger.info(f"Container {state.container_id[:12]} Docker status: {docker_status}")
        
        # Синхронизируем статус
        if docker_status == "running" and state.status != "running":
            logger.info(f"Updating state from '{state.status}' to 'running'")
            state.status = "running"
            save_state(state)
        elif docker_status == "exited" and state.status != "paused":
            logger.info(f"Container exited, updating state to 'paused'")
            state.status = "paused"
            save_state(state)
        elif docker_status in ["created", "restarting"]:
            logger.info(f"Container in transient state: {docker_status}")
        else:
            logger.info(f"State is in sync: {state.status}")
    else:
        logger.error(f"Failed to get Docker status for container {state.container_id[:12]}")


def check_docker_running() -> bool:
    """Проверяет, что Docker daemon запущен"""
    success, _, _ = run_command(["docker", "info"])
    if not success:
        logger.error("Docker daemon is not running or not accessible")
        return False
    return True

