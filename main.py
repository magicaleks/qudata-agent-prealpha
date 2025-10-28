import os
import signal
import subprocess
import sys
import time
from threading import Event, Thread
from typing import Optional

import psutil
from uvicorn import run

from src import runtime
from src.client.models import (
    ConfigurationData,
    CreateHost,
    InitAgent,
    InstanceStatus,
    Location,
    Stats,
    UnitValue,
)
from src.client.qudata import QudataClient
from src.runtime import agent_id, agent_port
from src.service.fingerprint import get_fingerprint
from src.service.gpu_info import (
    get_cpu_info,
    get_memory_speed,
    get_network_speed,
    get_nvidia_gpu_info,
)
from src.service.health import check_docker_running, sync_state_with_docker
from src.service.system_check import (
    check_all_requirements,
    install_missing_packages,
    print_system_status,
)
from src.storage.state import get_current_state
from src.utils.xlogging import get_logger

logger = get_logger(__name__)

shutdown_event = Event()
gunicorn_process: Optional[subprocess.Popen] = None


def format_gpu_name(gpu_name: str) -> str:
    """
    Форматирует имя GPU: убирает пробелы, приводит к uppercase, убирает интерфейсы
    """
    if not gpu_name or gpu_name.upper() in ["N/A", "UNKNOWN", "UNKNOWN NVIDIA GPU"]:
        return "GTX1080"

    # Убираем префиксы и интерфейсы
    formatted = gpu_name.upper()
    # Убираем общие префиксы
    formatted = formatted.replace("NVIDIA", "").replace("GEFORCE", "")
    # Убираем интерфейсы
    formatted = formatted.replace("PCI-E", "").replace("PCIE", "").replace("PCI", "")
    # Убираем пробелы, тире и прочее
    formatted = formatted.replace(" ", "").replace("-", "").replace("_", "")
    # Убираем лишние символы
    formatted = "".join(c for c in formatted if c.isalnum())

    # Если после обработки пусто
    if not formatted:
        return "GTX1080"

    return formatted

def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, initiating shutdown")
    shutdown_event.set()
    if gunicorn_process:
        gunicorn_process.terminate()


def collect_host_info() -> CreateHost:
    try:
        logger.info("Collecting host configuration...")

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        gpu_name, gpu_amount, vram, max_cuda = get_nvidia_gpu_info()
        cpu_name, cpu_freq = get_cpu_info()
        net_in, net_out = get_network_speed()
        mem_speed = get_memory_speed()

        host_info = CreateHost(
            gpu_name=format_gpu_name(gpu_name),
            gpu_amount=gpu_amount,
            vram=vram,
            location=Location(),
            configuration=ConfigurationData(
                ram=UnitValue(amount=round(mem.total / (1024**3), 2)),
                disk=UnitValue(amount=round(disk.total / (1024**3), 2)),
                vcpu=psutil.cpu_count(logical=True) or 1,
                cpu_cores=psutil.cpu_count(logical=False) or 1,
                cpu_name=cpu_name,
                cpu_freq=cpu_freq,
                memory_speed=mem_speed,
                ethernet_in=net_in,
                ethernet_out=net_out,
                max_cuda_version=max_cuda,
            ),
        )

        logger.info(
            f"Host info collected: GPU={gpu_name}x{gpu_amount}, RAM={host_info.configuration.ram.amount}GB"
        )
        return host_info

    except Exception as e:
        logger.error(f"Failed to collect host info: {e}", exc=e)
        return CreateHost(
            gpu_name="N/A",
            gpu_amount=0,
            vram=0.0,
            location=Location(),
            configuration=ConfigurationData(
                ram=UnitValue(
                    amount=round(psutil.virtual_memory().total / (1024**3), 2)
                ),
            ),
        )


def stats_heartbeat_thread():
    time.sleep(2)
    check_counter = 0
    
    while not shutdown_event.is_set():
        try:
            # Каждые 10 итераций (30 секунд) проверяем синхронизацию
            if check_counter % 10 == 0:
                sync_state_with_docker()
            check_counter += 1
            
            state = get_current_state()
            if state.status == "destroyed":
                shutdown_event.wait(3)
                continue

            try:
                container_status_enum = InstanceStatus(state.status)
            except ValueError:
                container_status_enum = InstanceStatus.error

            stats_data = Stats(
                cpu_util=psutil.cpu_percent(interval=1),
                ram_util=psutil.virtual_memory().percent,
                status=container_status_enum.value,
            )
            
            client = QudataClient()
            client.send_stats(stats_data)
            logger.info(f"Stats sent: {container_status_enum.value}")

        except Exception as e:
            logger.error(f"Failed to send stats: {e}")

        shutdown_event.wait(3)


def initialize_agent() -> bool:
    max_retries = 3
    retry_delay = 5

    logger.info("=== Starting agent initialization ===")
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Initializing agent (attempt {attempt}/{max_retries})")
            logger.info(f"  Agent ID: {agent_id()}")
            logger.info(f"  Agent Port: {agent_port()}")
            logger.info(f"  Agent Address: {runtime.agent_address()}")
            
            client = QudataClient()
            logger.info("  QudataClient created")

            init_data = InitAgent(
                agent_id=agent_id(),
                agent_port=agent_port(),
                address=runtime.agent_address(),
                fingerprint=get_fingerprint(),
                pid=runtime.agent_pid(),
            )
            logger.info("  Sending init request to API...")

            agent_response = client.init(init_data)
            logger.info(f"  Agent initialized: {agent_response.agent_created}")

            logger.info("  Collecting host info...")
            host_info = collect_host_info()
            
            logger.info("  Registering host with API...")
            client.create_host(host_info)
            logger.info("✓ Host registered successfully")

            return True

        except Exception as e:
            logger.error(f"✗ Initialization attempt {attempt} failed: {e}", exc=e)
            if attempt < max_retries:
                logger.info(f"  Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("✗ All initialization attempts failed")
                return False

    return False


def main():
    global gunicorn_process

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info("=== QuData Agent Starting ===")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Working directory: {os.getcwd()}")

        print_system_status()

        logger.info("Checking system requirements...")
        all_ok, missing = check_all_requirements()
        if not all_ok:
            logger.error(f"Missing required components: {', '.join(missing)}")
            logger.info("Attempting to install missing packages...")
            if not install_missing_packages():
                logger.error(
                    "Failed to install required packages. Please install them manually."
                )
                sys.exit(1)
        else:
            logger.info("✓ All system requirements met")
        
        # Проверяем Docker и синхронизируем состояние
        logger.info("Checking Docker status...")
        if check_docker_running():
            logger.info("✓ Docker is running, syncing state...")
            sync_state_with_docker()
        else:
            logger.error("✗ Docker is not running, cannot start agent")
            sys.exit(1)

        logger.info("Starting agent initialization...")
        if not initialize_agent():
            logger.error("✗ Failed to initialize agent, exiting")
            sys.exit(1)
        logger.info("✓ Agent initialization complete")

        logger.info("Starting background threads...")
        stats_thread = Thread(target=stats_heartbeat_thread, daemon=True)
        stats_thread.start()
        logger.info("✓ Stats heartbeat thread started")

        port = agent_port()
        # gunicorn_command = [
        #     sys.executable,
        #     "-m",
        #     "gunicorn",
        #     "-w",
        #     "2",
        #     "-b",
        #     f"0.0.0.0:{port}",
        #     "--timeout",
        #     "120",
        #     "--graceful-timeout",
        #     "30",
        #     "--chdir",
        #     ".",
        #     "src.server.server:app",
        # ]

        logger.info(f"Starting HTTP server on 0.0.0.0:{port}")
        logger.info("=== Agent is fully operational ===")
        run("src.server.server:app", host="0.0.0.0", port=port, log_level="warning")

    except KeyboardInterrupt:
        logger.info("Agent stopped by user")
    except Exception as e:
        logger.error(f"Agent error: {e}", exc=e)
        sys.exit(1)
    finally:
        shutdown_event.set()
        # if gunicorn_process:
        #     try:
        #         gunicorn_process.terminate()
        #         gunicorn_process.wait(timeout=10)
        #     except Exception as e:
        #         logger.error(f"Error terminating gunicorn: {e}")
        #         gunicorn_process.kill()
        logger.info("Agent shutdown complete")


if __name__ == "__main__":
    # Проверяем API ключ из аргументов или переменной окружения
    api_key = None
    
    # Приоритет 1: аргумент командной строки
    if len(sys.argv) >= 2:
        api_key = sys.argv[1]
    
    # Приоритет 2: переменная окружения
    if not api_key:
        api_key = os.environ.get("QUDATA_API_KEY")
    
    if not api_key:
        logger.error("API key not provided via QUDATA_API_KEY env var or command line. Exiting.")
        print("Usage: python main.py <API_KEY>")
        print("Or set QUDATA_API_KEY environment variable")
        sys.exit(1)
    
    # Устанавливаем API ключ как первый аргумент для совместимости с HttpClient
    if len(sys.argv) < 2:
        sys.argv.append(api_key)
    else:
        sys.argv[1] = api_key
    
    logger.info(f"Starting with API key: {api_key[:8]}...")
    main()
