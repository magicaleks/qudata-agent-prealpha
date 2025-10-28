"""Настройка SSH в контейнерах"""

from typing import Tuple, Optional

from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def setup_ssh_in_container(container_id: str) -> Tuple[bool, Optional[str]]:
    """
    Устанавливает и настраивает SSH сервер в контейнере.
    Gracefully обрабатывает ошибки - не все образы поддерживают SSH.
    
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
    
    # Проверяем, что контейнер запущен
    success, status, _ = run_command(
        ["docker", "inspect", "-f", "{{.State.Status}}", container_id]
    )
    if not success or status.strip() != "running":
        err = f"Container is not running (status: {status.strip()})"
        logger.warning(err)
        return False, err
    
    # Проверяем наличие apt-get (Debian/Ubuntu based образ)
    success, _, _ = run_command(
        ["docker", "exec", container_id, "which", "apt-get"]
    )
    if not success:
        logger.warning(f"Container {container_id[:12]} doesn't have apt-get, skipping SSH setup")
        return False, "Image doesn't support apt-get (not Debian/Ubuntu based)"
    
    # Команды для установки и настройки SSH
    setup_commands = [
        # Обновление списка пакетов
        "apt-get update -qq",
        
        # Установка OpenSSH сервера без интерактивных запросов
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server",
        
        # Создание директории для SSH daemon
        "mkdir -p /var/run/sshd",
        
        # Разрешение root login через SSH
        "sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config || true",
        "sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config || true",
        
        # Создание директории .ssh для root
        "mkdir -p /root/.ssh",
        "chmod 700 /root/.ssh",
        "touch /root/.ssh/authorized_keys",
        "chmod 600 /root/.ssh/authorized_keys",
    ]
    
    for cmd in setup_commands:
        logger.info(f"Executing: {cmd[:50]}...")
        success, _, stderr = run_command(
            ["docker", "exec", container_id, "sh", "-c", cmd],
            timeout=180  # 3 минуты на установку пакетов
        )
        
        if not success:
            # Некоторые команды могут выдавать warnings, но работать
            if "unable to resolve host" in stderr.lower() or "|| true" in cmd:
                logger.warning(f"Non-critical error: {stderr[:100]}")
                continue
            
            if "apt-get install" in cmd:
                logger.error(f"Failed to install SSH: {stderr[:200]}")
                return False, f"Failed to install openssh-server: {stderr[:200]}"
            
            logger.warning(f"Command failed but continuing: {stderr[:100]}")
    
    # Проверяем, что sshd установлен
    success, sshd_path, _ = run_command(
        ["docker", "exec", container_id, "which", "sshd"]
    )
    if not success or not sshd_path.strip():
        success, sshd_path, _ = run_command(
            ["docker", "exec", container_id, "test", "-f", "/usr/sbin/sshd"]
        )
        if not success:
            err = "SSH server binary not found after installation"
            logger.error(err)
            return False, err
    
    # Запуск SSH daemon
    logger.info("Starting SSH daemon...")
    success, _, stderr = run_command(
        ["docker", "exec", "-d", container_id, "/usr/sbin/sshd", "-D"]
    )
    
    if not success:
        err = f"Failed to start SSH daemon: {stderr[:200]}"
        logger.error(err)
        return False, err
    
    logger.info(f"✓ SSH daemon started successfully in container {container_id[:12]}")
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

