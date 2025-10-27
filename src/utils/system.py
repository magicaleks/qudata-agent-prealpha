import shutil
import subprocess
from typing import Optional, List, Tuple

from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def run_command(
    command: List[str],
    input_data: Optional[str] = None,
) -> Tuple[bool, str, str]:
    try:
        executable = command[0]
        if not shutil.which(executable):
            error_msg = f"Command not found: {executable}"
            logger.error(error_msg)
            return False, "", error_msg

        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            input=input_data,
            check=False,
            timeout=120,
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
        error_msg = f"Command '{' '.join(command)}' timed out after 120 seconds."
        logger.error(error_msg)
        return False, "", error_msg
    except Exception as e:
        error_msg = (
            f"An unexpected error occurred while "
            f"running command '{' '.join(command)}': {e}"
        )
        logger.error(error_msg, exc=e)
        return False, "", str(e)
