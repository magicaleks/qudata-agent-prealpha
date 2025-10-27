"""Управление SSH ключами в контейнерах"""

from typing import Tuple, Optional

from src.service.ssh_setup import restart_ssh_in_container
from src.storage.state import get_current_state
from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def add_ssh_key_to_container(ssh_pubkey: str) -> Tuple[bool, Optional[str]]:
    """Добавляет SSH публичный ключ в контейнер"""
    
    if not ssh_pubkey or not ssh_pubkey.strip():
        err = "SSH public key is empty"
        logger.error(err)
        return False, err
    
    state = get_current_state()
    
    if state.status == "destroyed" or not state.container_id:
        err = "No active container to add SSH key to"
        logger.error(err)
        return False, err
    
    container_id = state.container_id
    logger.info(f"Adding SSH key to container {container_id[:12]}")
    
    # Проверяем, что контейнер запущен
    success, status, _ = run_command(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_id]
    )
    
    if not success or status.strip().lower() != "running":
        err = f"Container is not running (status: {status.strip() if success else 'unknown'})"
        logger.error(err)
        return False, err
    
    # Создаём директорию .ssh если её нет
    commands = [
        "mkdir -p /root/.ssh",
        "chmod 700 /root/.ssh",
        "touch /root/.ssh/authorized_keys",
        "chmod 600 /root/.ssh/authorized_keys",
    ]
    
    for cmd in commands:
        success, _, stderr = run_command(
            ["docker", "exec", container_id, "sh", "-c", cmd]
        )
        if not success:
            logger.warning(f"Command '{cmd}' failed: {stderr}")
    
    # Добавляем ключ в authorized_keys
    # Экранируем ключ для безопасной передачи
    escaped_key = ssh_pubkey.strip().replace("'", "'\\''")
    add_key_cmd = f"echo '{escaped_key}' >> /root/.ssh/authorized_keys"
    
    success, _, stderr = run_command(
        ["docker", "exec", container_id, "sh", "-c", add_key_cmd]
    )
    
    if not success:
        err = f"Failed to add SSH key: {stderr}"
        logger.error(err)
        return False, err
    
    logger.info(f"SSH key added successfully to container {container_id[:12]}")
    
    # Перезапускаем SSH daemon для применения изменений
    restart_ssh_in_container(container_id)
    
    return True, None


def remove_ssh_key_from_container(ssh_pubkey: str) -> Tuple[bool, Optional[str]]:
    """Удаляет SSH публичный ключ из контейнера"""
    
    if not ssh_pubkey or not ssh_pubkey.strip():
        err = "SSH public key is empty"
        logger.error(err)
        return False, err
    
    state = get_current_state()
    
    if state.status == "destroyed" or not state.container_id:
        err = "No active container to remove SSH key from"
        logger.error(err)
        return False, err
    
    container_id = state.container_id
    logger.info(f"Removing SSH key from container {container_id[:12]}")
    
    # Проверяем, что контейнер запущен
    success, status, _ = run_command(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_id]
    )
    
    if not success or status.strip().lower() != "running":
        err = f"Container is not running (status: {status.strip() if success else 'unknown'})"
        logger.error(err)
        return False, err
    
    # Удаляем ключ из authorized_keys
    # Экранируем ключ для безопасной передачи
    escaped_key = ssh_pubkey.strip().replace("'", "'\\''").replace("/", "\\/")
    remove_key_cmd = f"sed -i '/{escaped_key}/d' /root/.ssh/authorized_keys 2>/dev/null || true"
    
    success, _, stderr = run_command(
        ["docker", "exec", container_id, "sh", "-c", remove_key_cmd]
    )
    
    if not success:
        err = f"Failed to remove SSH key: {stderr}"
        logger.error(err)
        return False, err
    
    logger.info(f"SSH key removed successfully from container {container_id[:12]}")
    
    # Перезапускаем SSH daemon для применения изменений
    restart_ssh_in_container(container_id)
    
    return True, None


def list_ssh_keys_in_container() -> Tuple[bool, Optional[str], Optional[str]]:
    """Получает список SSH ключей из контейнера"""
    
    state = get_current_state()
    
    if state.status == "destroyed" or not state.container_id:
        err = "No active container to list SSH keys from"
        logger.error(err)
        return False, None, err
    
    container_id = state.container_id
    logger.info(f"Listing SSH keys in container {container_id[:12]}")
    
    # Читаем authorized_keys
    success, keys, stderr = run_command(
        ["docker", "exec", container_id, "cat", "/root/.ssh/authorized_keys"]
    )
    
    if not success:
        if "No such file" in stderr:
            logger.info("No authorized_keys file found, returning empty list")
            return True, "", None
        else:
            err = f"Failed to read SSH keys: {stderr}"
            logger.error(err)
            return False, None, err
    
    logger.info(f"Found {len(keys.strip().split(chr(10))) if keys.strip() else 0} SSH keys")
    return True, keys, None

