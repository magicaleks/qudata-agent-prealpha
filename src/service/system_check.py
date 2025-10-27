import shutil
import subprocess
from typing import Dict, List, Tuple

from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


REQUIRED_COMMANDS = {
    "docker": "Docker",
    "nvidia-smi": "NVIDIA Driver",
    "lscpu": "CPU utilities",
}

OPTIONAL_COMMANDS = {
    "ethtool": "Network tools",
    "dmidecode": "Hardware info tools",
}


def check_command(command: str) -> bool:
    """Проверяет наличие команды в системе"""
    return shutil.which(command) is not None


def check_docker_nvidia() -> bool:
    """Проверяет поддержку NVIDIA в Docker"""
    try:
        success, output, _ = run_command(
            [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "nvidia/cuda:11.0-base",
                "nvidia-smi",
            ]
        )
        return success
    except Exception:
        return False


def check_all_requirements() -> Tuple[bool, List[str]]:
    """
    Проверяет все требования системы.
    Возвращает: (все_ок, список_отсутствующих)
    """
    missing = []

    for cmd, name in REQUIRED_COMMANDS.items():
        if not check_command(cmd):
            missing.append(f"{name} ({cmd})")
            logger.error(f"Required command not found: {cmd}")

    for cmd, name in OPTIONAL_COMMANDS.items():
        if not check_command(cmd):
            logger.warning(f"Optional command not found: {cmd}")

    if check_command("docker"):
        success, output, _ = run_command(["docker", "info"])
        if not success:
            missing.append("Docker daemon (not running)")
            logger.error("Docker daemon is not running")

    return len(missing) == 0, missing


def install_missing_packages() -> bool:
    """Пытается установить недостающие пакеты (требует sudo)"""
    try:
        logger.info("Checking for missing packages...")

        all_ok, missing = check_all_requirements()
        if all_ok:
            logger.info("All required packages are installed")
            return True

        logger.warning(f"Missing packages: {', '.join(missing)}")

        packages_to_install = []

        if not check_command("docker"):
            logger.error("Docker is not installed. Please install Docker manually:")
            logger.error("  curl -fsSL https://get.docker.com -o get-docker.sh")
            logger.error("  sudo sh get-docker.sh")
            return False

        if not check_command("nvidia-smi"):
            logger.error(
                "NVIDIA drivers are not installed. Please install NVIDIA drivers manually:"
            )
            logger.error("  sudo apt-get install nvidia-driver-535")
            return False

        if not check_command("ethtool"):
            packages_to_install.append("ethtool")

        if not check_command("dmidecode"):
            packages_to_install.append("dmidecode")

        if packages_to_install:
            logger.info(
                f"Installing optional packages: {', '.join(packages_to_install)}"
            )
            cmd = ["sudo", "apt-get", "install", "-y"] + packages_to_install
            success, _, _ = run_command(cmd)
            if success:
                logger.info("Optional packages installed successfully")
            else:
                logger.warning(
                    "Failed to install some optional packages, continuing anyway"
                )

        return True

    except Exception as e:
        logger.error(f"Failed to install packages: {e}")
        return False


def get_system_status() -> Dict[str, bool]:
    """Возвращает статус всех системных компонентов"""
    status = {}

    for cmd in REQUIRED_COMMANDS:
        status[cmd] = check_command(cmd)

    for cmd in OPTIONAL_COMMANDS:
        status[cmd] = check_command(cmd)

    if check_command("docker"):
        success, _, _ = run_command(["docker", "info"])
        status["docker_running"] = success

        if check_command("nvidia-smi"):
            status["docker_nvidia"] = check_docker_nvidia()

    return status


def print_system_status():
    """Выводит статус системы в лог"""
    status = get_system_status()

    logger.info("=== System Status ===")
    for component, available in status.items():
        status_str = "✓" if available else "✗"
        logger.info(f"{status_str} {component}")
    logger.info("====================")
