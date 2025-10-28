import shutil
import subprocess
from typing import Optional, List, Tuple

from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def run_command(
    command: List[str],
    input_data: Optional[str] = None,
    timeout: Optional[int] = 120,
) -> Tuple[bool, str, str]:
    """
    Выполняет команду с опциональным таймаутом.
    
    Args:
        command: Список аргументов команды
        input_data: Входные данные для stdin
        timeout: Таймаут в секундах, None = без таймаута
    """
    try:
        executable = command[0]
        if not shutil.which(executable):
            error_msg = f"Command not found: {executable}"
            logger.error(error_msg)
            return False, "", error_msg

        # Для docker run используем больший таймаут или без таймаута
        effective_timeout = timeout
        if command[0] == "docker" and len(command) > 1 and command[1] == "run":
            effective_timeout = 600  # 10 минут для docker run (pull + start)
            logger.info(f"Using extended timeout ({effective_timeout}s) for docker run")

        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            input=input_data,
            check=False,
            timeout=effective_timeout,
            encoding="utf-8",
            errors="ignore",
        )

        if process.returncode != 0:
            stderr_output = process.stderr.strip()
            return False, process.stdout.strip(), stderr_output

        return True, process.stdout.strip(), process.stderr.strip()

    except FileNotFoundError:
        error_msg = (
            f"Critical error: "
            f"Command executable '{command[0]}' not found during run."
        )
        logger.error(error_msg)
        return False, "", error_msg
    except subprocess.TimeoutExpired:
        timeout_val = timeout if timeout else "infinite"
        error_msg = f"Command '{' '.join(command)}' timed out after {timeout_val} seconds."
        logger.error(error_msg)
        return False, "", error_msg
    except Exception as e:
        error_msg = (
            f"An unexpected error occurred while "
            f"running command '{' '.join(command)}': {e}"
        )
        logger.error(error_msg, exc=e)
        return False, "", str(e)
