"""Настройка SSH в контейнерах"""

from typing import Tuple, Optional

from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def setup_ssh_in_container(container_id: str) -> Tuple[bool, Optional[str]]:
    """
    Устанавливает и настраивает SSH сервер в контейнере
    
    Args:
        container_id: ID контейнера Docker
        
    Returns:
        (success, error_message)
    """
    if not container_id:
        err = "No container ID provided"
        logger.error(err)
        return False, err
    
    logger.info(f"Setting up SSH in container {container_id[:12]}")
    
    # Команды для установки и настройки SSH
    setup_commands = [
        # Обновление списка пакетов
        "apt-get update -qq",
        
        # Установка OpenSSH сервера без интерактивных запросов
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server",
        
        # Создание директории для SSH daemon
        "mkdir -p /var/run/sshd",
        
        # Разрешение root login через SSH
        "sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config",
        "sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config",
        
        # Создание директории .ssh для root
        "mkdir -p /root/.ssh",
        "chmod 700 /root/.ssh",
        "touch /root/.ssh/authorized_keys",
        "chmod 600 /root/.ssh/authorized_keys",
    ]
    
    for cmd in setup_commands:
        logger.info(f"Executing: {cmd}")
        success, _, stderr = run_command(
            ["docker", "exec", container_id, "sh", "-c", cmd]
        )
        
        if not success:
            # Некоторые команды могут выдавать warnings, но работать
            if "unable to resolve host" in stderr.lower():
                logger.warning(f"Warning during SSH setup: {stderr}")
                continue
            
            logger.error(f"Failed to execute command '{cmd}': {stderr}")
            # Продолжаем даже при ошибках некоторых команд
    
    # Запуск SSH daemon
    logger.info("Starting SSH daemon")
    success, _, stderr = run_command(
        ["docker", "exec", "-d", container_id, "/usr/sbin/sshd", "-D"]
    )
    
    if not success:
        err = f"Failed to start SSH daemon: {stderr}"
        logger.error(err)
        return False, err
    
    logger.info(f"SSH daemon started successfully in container {container_id[:12]}")
    return True, None


def restart_ssh_in_container(container_id: str) -> Tuple[bool, Optional[str]]:
    """Перезапускает SSH сервер в контейнере"""
    if not container_id:
        err = "No container ID provided"
        logger.error(err)
        return False, err
    
    logger.info(f"Restarting SSH in container {container_id[:12]}")
    
    # Останавливаем все процессы sshd
    run_command(["docker", "exec", container_id, "pkill", "-9", "sshd"])
    
    # Запускаем заново
    success, _, stderr = run_command(
        ["docker", "exec", "-d", container_id, "/usr/sbin/sshd", "-D"]
    )
    
    if not success:
        err = f"Failed to restart SSH daemon: {stderr}"
        logger.error(err)
        return False, err
    
    logger.info(f"SSH daemon restarted successfully in container {container_id[:12]}")
    return True, None

