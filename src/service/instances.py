import time
import uuid
from dataclasses import asdict
from threading import Thread
from typing import Optional, Tuple, Dict, Any

from src.server.models import (
    CreateInstance,
    InstanceAction,
    InstanceCreated,
    ManageInstance,
)
from src.service.ssh_setup import setup_ssh_in_container, restart_ssh_in_container
from src.storage.state import InstanceState, clear_state, get_current_state, save_state
from src.utils.ports import get_free_port
from src.utils.system import run_command
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def check_container_exists(container_id: str) -> bool:
    """Проверяет, существует ли контейнер в Docker"""
    if not container_id:
        return False
    
    success, output, stderr = run_command(["docker", "inspect", container_id])
    
    # Дополнительная проверка на "No such object"
    if not success and ("No such" in stderr or "not found" in stderr.lower()):
        return False
    
    return success


def create_new_instance(
    params: CreateInstance,
    preallocated_ports: Optional[Dict[str, str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    try:
        state = get_current_state()
        
        # Проверяем синхронизацию состояния с Docker
        if state.status != "destroyed":
            if state.container_id and not check_container_exists(state.container_id):
                logger.warning(f"Container {state.container_id[:12]} in state but not in Docker, cleaning up state")
                clear_state()
                state = get_current_state()
            else:
                err = f"An instance '{state.instance_id}' already exists with status '{state.status}'. Please delete it first."
                logger.error(err)
                return False, None, err

        if not params.image:
            err = "Image is required"
            logger.error(err)
            return False, None, err

        # Обрабатываем формат образа: если в image уже есть тег, используем его
        if ":" in params.image and not params.image.endswith(":"):
            # Образ уже содержит тег, например nvidia/cuda:12.6.1-base-ubuntu22.04
            image_full_name = params.image
            logger.info(f"Using image with embedded tag: {image_full_name}")
        else:
            # Образ без тега или с : в конце, добавляем image_tag
            image_tag = params.image_tag if params.image_tag and params.image_tag != "latest" else "latest"
            image_full_name = f"{params.image.rstrip(':')}:{image_tag}"
            logger.info(f"Constructing image name: {image_full_name}")

        logger.info(f"Creating instance with image {image_full_name}")
        instance_id = str(uuid.uuid4())

        env_vars = params.env_variables.copy() if params.env_variables else {}
        cpu_cores = env_vars.pop("QUDATA_CPU_CORES", "1")
        memory_gb = env_vars.pop("QUDATA_MEMORY_GB", "2")
        gpu_count = env_vars.pop("QUDATA_GPU_COUNT", "0")
    except Exception as e:
        logger.error(f"Error in initial instance creation setup: {e}", exc=e)
        return False, None, f"Setup error: {str(e)}"

    docker_command = [
        "docker",
        "run",
        "-d",
        f"--cpus={cpu_cores}",
        f"--memory={memory_gb}g",
    ]

    if int(gpu_count) > 0:
        docker_command.append(f"--gpus=count={gpu_count}")

    # Используем предвыделенные порты или выделяем новые
    if preallocated_ports:
        logger.info(f"Using preallocated ports: {preallocated_ports}")
        allocated_ports = preallocated_ports.copy()
    else:
        logger.info("Allocating new ports...")
        allocated_ports = {}
        for container_port, host_port_def in (params.ports or {}).items():
            host_port = str(
                host_port_def if str(host_port_def).lower() != "auto" else get_free_port()
            )
            allocated_ports[container_port] = host_port
        
        if params.ssh_enabled and "22" not in (params.ports or {}):
            host_ssh_port = str(get_free_port())
            allocated_ports["22"] = host_ssh_port

    # Добавляем порты в docker команду
    for container_port, host_port in allocated_ports.items():
        docker_command.extend(["-p", f"{host_port}:{container_port}"])
        logger.info(f"  Mapping port: {container_port} -> {host_port}")

    # Добавляем переменные окружения
    for key, value in env_vars.items():
        if not key or not isinstance(key, str):
            continue
        docker_command.extend(["-e", f"{key}={value}"])

    docker_command.append(image_full_name)
    
    # Обработка команды для запуска в контейнере
    if params.command:
        # Если команда содержит shell операторы (&&, ||, |, ;, etc.), оборачиваем в sh -c
        shell_operators = ["&&", "||", "|", ";", ">", "<", "$(", "`"]
        needs_shell = any(op in params.command for op in shell_operators)
        
        if needs_shell:
            logger.info(f"Command contains shell operators, wrapping in 'sh -c': {params.command}")
            docker_command.extend(["sh", "-c", params.command])
        else:
            # Простая команда без операторов - можно разбить по пробелам
            docker_command.extend(params.command.split())
            logger.info(f"Simple command: {params.command}")
    else:
        # Используем tail -f /dev/null для поддержания контейнера в рабочем состоянии
        docker_command.extend(["tail", "-f", "/dev/null"])
        logger.info("No command specified, using idle mode: tail -f /dev/null")

    try:
        logger.info(f"Executing docker run command")
        logger.info(f"Docker command preview: docker run -d --cpus={cpu_cores} --memory={memory_gb}g ... {image_full_name}")
        logger.info(f"Full command: {' '.join(docker_command)}")
        success, container_id, stderr = run_command(docker_command)
        
        if not success or not container_id:
            logger.error(f"Docker run failed: {stderr}")
            return False, None, f"Failed to run Docker container: {stderr}"

        container_id = container_id.strip()
        logger.info(f"Container '{container_id[:12]}' created, checking status...")
        
        # Проверяем статус контейнера через пару секунд
        time.sleep(2)
        
        success, status, _ = run_command(
            ["docker", "inspect", "-f", "{{.State.Status}}", container_id]
        )
        
        if not success or status.strip() != "running":
            # Контейнер не запустился или упал
            logger.error(f"Container {container_id[:12]} is not running (status: {status.strip()})")
            
            # Получаем логи контейнера для диагностики
            _, logs, _ = run_command(["docker", "logs", container_id])
            logger.error(f"Container logs: {logs[:500]}")
            
            # Удаляем упавший контейнер
            run_command(["docker", "rm", "-f", container_id])
            
            return False, None, f"Container failed to start (status: {status.strip()}). Logs: {logs[:200]}"
        
        logger.info(f"✓ Container '{container_id[:12]}' is running")

        # Если SSH включен, настраиваем SSH в контейнере в фоновом режиме
        if params.ssh_enabled:
            logger.info(f"SSH is enabled, starting SSH setup in background for container {container_id[:12]}")
            
            def setup_ssh_background():
                ssh_success, ssh_error = setup_ssh_in_container(container_id)
                if not ssh_success:
                    logger.warning(f"Failed to setup SSH in background: {ssh_error}")
                else:
                    logger.info(f"SSH setup completed successfully in container {container_id[:12]}")
            
            ssh_thread = Thread(target=setup_ssh_background, daemon=True, name=f"ssh-setup-{container_id[:12]}")
            ssh_thread.start()
            logger.info(f"SSH setup started in background thread")

        new_state = InstanceState(
            instance_id=instance_id,
            container_id=container_id,
            status="running",
            allocated_ports=allocated_ports,
        )
        
        if not save_state(new_state):
            logger.error("Failed to save state, rolling back")
            run_command(["docker", "rm", "-f", container_id])
            return (
                False,
                None,
                "CRITICAL: Failed to save state after container creation. Rolled back.",
            )

        created_data = InstanceCreated(success=True, ports=allocated_ports)
        logger.info(f"Instance creation successful: ports={allocated_ports}")
        return True, asdict(created_data), None
        
    except Exception as e:
        logger.error(f"Unexpected error during container creation: {e}", exc=e)
        return False, None, f"Unexpected error: {str(e)}"


def manage_instance(params: ManageInstance) -> Tuple[bool, Optional[str]]:
    state = get_current_state()
    if state.status == "destroyed" or not state.container_id:
        err = "No active instance to manage"
        logger.error(err)
        return False, err

    container_id = state.container_id
    
    # Проверяем, существует ли контейнер
    if not check_container_exists(container_id):
        err = f"Container {container_id[:12]} not found in Docker, clearing state"
        logger.error(err)
        clear_state()
        return False, err

    # Получаем текущий статус контейнера из Docker
    success, docker_status, _ = run_command(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_id]
    )
    
    if success:
        docker_status = docker_status.strip().lower()
        logger.info(f"Container {container_id[:12]} Docker status: {docker_status}")
    else:
        logger.warning(f"Failed to get Docker status for container {container_id[:12]}")
        docker_status = "unknown"

    action_map = {
        "stop": (["docker", "stop", container_id], "paused"),
        "start": (["docker", "start", container_id], "running"),
        "restart": (["docker", "restart", container_id], "running"),
    }

    if params.action not in action_map:
        err = f"Unknown action: {params.action}"
        logger.error(err)
        return False, err

    command, new_status = action_map[params.action]

    # Проверяем валидность действия относительно текущего статуса
    if params.action == "start" and docker_status == "running":
        logger.warning(f"Container {container_id[:12]} is already running")
        state.status = "running"
        save_state(state)
        return True, None
    elif params.action == "stop" and docker_status == "exited":
        logger.warning(f"Container {container_id[:12]} is already stopped")
        state.status = "paused"
        save_state(state)
        return True, None

    logger.info(
        f"Executing action '{params.action}' on container {container_id[:12]} (current status: {docker_status})..."
    )
    success, output, stderr = run_command(command)

    if success:
        state.status = new_status
        save_state(state)
        logger.info(f"Action '{params.action}' completed successfully, new status: {new_status}")
        
        # Если контейнер был запущен или перезапущен, перезапускаем SSH daemon в фоне
        if params.action in ["start", "restart"]:
            logger.info(f"Restarting SSH daemon after {params.action}")
            
            def restart_ssh_background():
                ssh_success, ssh_error = restart_ssh_in_container(container_id)
                if not ssh_success:
                    logger.warning(f"Failed to restart SSH daemon: {ssh_error}")
            
            ssh_thread = Thread(target=restart_ssh_background, daemon=True, name=f"ssh-restart-{container_id[:12]}")
            ssh_thread.start()
        
        return True, None
    else:
        # Проверяем, не исчез ли контейнер
        if "No such container" in stderr or "no such container" in stderr.lower():
            logger.warning(f"Container {container_id[:12]} disappeared, clearing state")
            clear_state()
            return False, "Container no longer exists, state cleared"
        
        err = f"Failed to execute action '{params.action}': {stderr}"
        logger.error(err)
        
        # Синхронизируем статус с реальным состоянием
        if check_container_exists(container_id):
            success_inspect, docker_status_new, _ = run_command(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_id]
            )
            if success_inspect:
                docker_status_new = docker_status_new.strip().lower()
                if docker_status_new == "running":
                    state.status = "running"
                elif docker_status_new == "exited":
                    state.status = "paused"
                else:
                    state.status = "error"
                save_state(state)
                logger.info(f"Synced status with Docker: {state.status}")
            else:
                state.status = "error"
                save_state(state)
        else:
            logger.warning(f"Container {container_id[:12]} no longer exists after failed action")
            clear_state()
            return False, "Container no longer exists, state cleared"
        
        return False, err


def delete_instance() -> Tuple[bool, Optional[str]]:
    state = get_current_state()
    if state.status == "destroyed":
        logger.info("No instance to delete")
        return True, None

    if state.container_id:
        container_id = state.container_id
        logger.info(f"Removing container {container_id[:12]}")
        
        # Проверяем существование контейнера
        if check_container_exists(container_id):
            # Останавливаем и удаляем контейнер
            success, _, stderr = run_command(["docker", "rm", "-f", container_id])
            if success:
                logger.info(f"Container {container_id[:12]} removed successfully")
            else:
                logger.warning(f"Failed to remove container {container_id[:12]}: {stderr}")
        else:
            logger.warning(f"Container {container_id[:12]} not found in Docker, cleaning state only")

    clear_state()
    logger.info("Instance deleted successfully")
    return True, None


def get_instance_logs(
    container_id: str, tail: int = 100
) -> Tuple[bool, Optional[str], Optional[str]]:
    if not container_id:
        err = "No container ID provided"
        logger.error(err)
        return False, None, err
    
    # Проверяем существование контейнера
    if not check_container_exists(container_id):
        err = f"Container {container_id[:12]} not found"
        logger.error(err)
        return False, None, err

    logger.info(f"Fetching logs for container {container_id[:12]}")
    command = ["docker", "logs", f"--tail={tail}", container_id]

    success, stdout, stderr = run_command(command)

    if success:
        return True, stdout or stderr, None
    else:
        # Проверяем, не исчез ли контейнер
        if "No such container" in stderr or "not found" in stderr.lower():
            logger.warning(f"Container {container_id[:12]} disappeared while fetching logs")
            return False, None, "Container no longer exists"
        
        full_log_output = f"STDERR: {stderr}\nSTDOUT: {stdout}"
        logger.error(f"Failed to fetch logs: {full_log_output[:200]}")
        return False, None, full_log_output
