import os
import signal
import subprocess
import sys
import time
import json
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
            gpu_amount=gpu_amount or 1,
            vram=vram or 4,
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
    """Упрощённая инициализация агента без ретраев"""
    logger.info("=" * 60)
    logger.info("STARTING AGENT INITIALIZATION")
    logger.info("=" * 60)

    try:
        # === ШАГ 1: Собираем данные ===
        agent_id_val = agent_id()
        agent_port_val = agent_port()
        agent_address_val = runtime.agent_address()
        fingerprint_val = get_fingerprint()
        pid_val = runtime.agent_pid()

        # === ШАГ 2: Логируем каждое значение через logger ===
        logger.info(f"--- Init Data Collection ---")
        logger.info(f"  agent_id: {agent_id_val} (type: {type(agent_id_val)})")
        logger.info(
            f"  agent_port: {agent_port_val} (type: {type(agent_port_val)})")
        logger.info(
            f"  address: {agent_address_val} (type: {type(agent_address_val)})")
        logger.info(
            f"  fingerprint: {fingerprint_val} (type: {type(fingerprint_val)})")
        logger.info(f"  pid: {pid_val} (type: {type(pid_val)})")
        logger.info(f"--------------------------")

        init_data = InitAgent(
            agent_id=agent_id_val,
            agent_port=agent_port_val,
            address=agent_address_val,
            fingerprint=fingerprint_val,
            pid=pid_val,
        )

        from src.utils.dto import to_json
        logger.info(
            f"Prepared JSON data for /init: {json.dumps(to_json(init_data), indent=2)}")

        # === ШАГ 4: Отправляем запрос ===
        logger.info("Creating QudataClient...")
        client = QudataClient()

        logger.info("Sending init request to API server...")
        agent_response = client.init(init_data)

        logger.info(
            f"✓ Agent initialized! Created: {agent_response.agent_created}")

        # === ШАГ 5: Собираем информацию о хосте и регистрируем его ===
        logger.info("Collecting host hardware info...")
        host_info = collect_host_info()

        logger.info("Registering host with API server...")
        client.create_host(host_info)

        logger.info("✓ HOST REGISTERED SUCCESSFULLY!")
        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.error(f"✗ INITIALIZATION FAILED: {e}")

        if hasattr(e, 'response') and e.response is not None:
            logger.error("-" * 20 + " SERVER RESPONSE " + "-" * 20)
            logger.error(f"Status Code: {e.response.status_code}")
            try:
                response_json = e.response.json()
                logger.error("Response JSON Body:")
                logger.error(json.dumps(response_json, indent=2))
            except Exception:
                logger.error("Response Text Body (not JSON):")
                logger.error(e.response.text)
            logger.error("-" * 57)

        logger.error("Full traceback:", exc_info=True)
        return False


def main():
    global gunicorn_process

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("\n" + "=" * 70)
    print("QUDATA AGENT STARTING")
    print("=" * 70)
    
    try:
        logger.info("=== QuData Agent Starting ===")
        logger.info(f"Python: {sys.version}")
        logger.info(f"Working dir: {os.getcwd()}")
        
        print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        print(f"Working directory: {os.getcwd()}")
        print()

        # Системные проверки
        print("Step 1/5: System checks...")
        print_system_status()

        all_ok, missing = check_all_requirements()
        if not all_ok:
            print(f"✗ Missing: {', '.join(missing)}")
            logger.error(f"Missing components: {', '.join(missing)}")
            print("Attempting to install...")
            if not install_missing_packages():
                print("✗ Failed to install packages")
                sys.exit(1)
        print("✓ System requirements OK\n")
        
        # Docker проверка
        print("Step 2/5: Docker check...")
        if not check_docker_running():
            print("✗ Docker is not running!")
            logger.error("Docker is not running")
            sys.exit(1)
        print("✓ Docker is running")
        sync_state_with_docker()
        print()

        # Инициализация агента
        print("Step 3/5: Agent initialization...")
        if not initialize_agent():
            print("✗ AGENT INITIALIZATION FAILED")
            logger.error("Agent initialization failed")
            sys.exit(1)
        print()

        # Запуск фоновых задач
        print("Step 4/5: Starting background tasks...")
        stats_thread = Thread(target=stats_heartbeat_thread, daemon=True)
        stats_thread.start()
        print("✓ Stats heartbeat thread started\n")
        logger.info("Stats heartbeat thread started")

        # Запуск веб-сервера
        print("Step 5/5: Starting HTTP server...")
        port = agent_port()
        print(f"✓ Server will listen on 0.0.0.0:{port}")
        print("=" * 70)
        print("AGENT IS FULLY OPERATIONAL")
        print("=" * 70)
        print()
        
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
