import re
from typing import List, Optional, Tuple

from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def get_nvidia_gpu_info() -> Tuple[str, int, float, Optional[float]]:
    """
    Возвращает: (gpu_name, gpu_count, vram_per_gpu_gb, max_cuda_version)
    """
    try:
        success, output, _ = run_command(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ]
        )

        if not success or not output:
            logger.warning("nvidia-smi not available or no GPUs found")
            return "N/A", 0, 0.0, None

        lines = [line.strip() for line in output.strip().split("\n") if line.strip()]

        if not lines:
            return "N/A", 0, 0.0, None

        gpu_count = len(lines)
        first_line = lines[0].split(",")

        if len(first_line) >= 2:
            gpu_name = first_line[0].strip()
            vram_mb = float(first_line[1].strip())
            vram_gb = round(vram_mb / 1024, 2)
        else:
            gpu_name = "Unknown NVIDIA GPU"
            vram_gb = 0.0

        cuda_version = get_cuda_version()

        logger.info(
            f"GPU detected: {gpu_name} x{gpu_count}, VRAM: {vram_gb}GB, CUDA: {cuda_version}"
        )
        return gpu_name, gpu_count, vram_gb, cuda_version

    except Exception as e:
        logger.error(f"Failed to get GPU info: {e}")
        return "N/A", 0, 0.0, None


def get_cuda_version() -> Optional[float]:
    """Получает максимальную версию CUDA"""
    try:
        success, output, _ = run_command(["nvidia-smi"])
        if not success or not output:
            return None

        match = re.search(r"CUDA Version:\s*(\d+\.\d+)", output)
        if match:
            return float(match.group(1))

        return None
    except Exception:
        return None


def get_cpu_info() -> Tuple[Optional[str], Optional[float]]:
    """Возвращает: (cpu_name, cpu_freq_ghz)"""
    try:
        success, output, _ = run_command(["lscpu"])
        if not success:
            return None, None

        cpu_name = None
        cpu_freq = None

        for line in output.split("\n"):
            if "Model name:" in line:
                cpu_name = line.split(":", 1)[1].strip()
            elif "CPU MHz:" in line:
                try:
                    mhz = float(line.split(":", 1)[1].strip())
                    cpu_freq = round(mhz / 1000, 2)
                except Exception:
                    pass

        return cpu_name, cpu_freq

    except Exception as e:
        logger.error(f"Failed to get CPU info: {e}")
        return None, None


def get_network_speed() -> Tuple[Optional[float], Optional[float]]:
    """Возвращает скорость сети в Gbps: (in, out)"""
    try:
        success, output, _ = run_command(["ethtool", "eth0"])
        if not success:
            interfaces = ["enp0s3", "ens3", "enp1s0", "ens4"]
            for iface in interfaces:
                success, output, _ = run_command(["ethtool", iface])
                if success:
                    break

        if not success or not output:
            return None, None

        match = re.search(r"Speed:\s*(\d+)Mb/s", output)
        if match:
            mbps = int(match.group(1))
            gbps = round(mbps / 1000, 2)
            return gbps, gbps

        return None, None

    except Exception:
        return None, None


def get_memory_speed() -> Optional[float]:
    """Возвращает скорость RAM в MHz"""
    try:
        success, output, _ = run_command(["dmidecode", "-t", "memory"])
        if not success or not output:
            return None

        speeds: List[int] = []
        for line in output.split("\n"):
            if "Speed:" in line and "MHz" in line:
                match = re.search(r"(\d+)\s*MHz", line)
                if match:
                    speeds.append(int(match.group(1)))

        if speeds:
            return float(max(speeds))

        return None

    except Exception:
        return None
