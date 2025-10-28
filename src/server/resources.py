from dataclasses import asdict
from threading import Thread

import falcon
import psutil
from falcon.asgi import Request, Response

from src.client.models import InstanceStatus, Stats
from src.client.qudata import QudataClient
from src.server.models import CreateInstance, ManageInstance
from src.service import instances
from src.service.ssh_keys import add_ssh_key_to_container, remove_ssh_key_from_container, list_ssh_keys_in_container
from src.storage import state as state_manager
from src.utils.dto import from_json
from src.utils.xlogging import get_logger

logger = get_logger(__name__)


def send_stats_async():
    def _send():
        try:
            state = state_manager.get_current_state()
            if state.status == "destroyed":
                logger.info("Skip sending stats: no active instance")
                return

            try:
                status_enum = InstanceStatus(state.status)
            except ValueError:
                status_enum = InstanceStatus.error
                logger.warning(f"Invalid instance status: {state.status}, using 'error'")

            stats = Stats(
                cpu_util=psutil.cpu_percent(interval=1),
                ram_util=psutil.virtual_memory().percent,
                status=status_enum.value,
            )

            client = QudataClient()
            client.send_stats(stats)
            logger.info(f"Stats sent after instance action: status={status_enum.value}, cpu={stats.cpu_util}%, ram={stats.ram_util}%")
        except Exception as e:
            logger.error(f"Failed to send stats after action: {e}", exc=e)

    Thread(target=_send, daemon=True).start()


class PingResource:

    async def on_get(self, req: Request, resp: Response) -> None:
        logger.info(f"Ping request from {req.remote_addr}")
        resp.status = falcon.HTTP_200
        resp.context["result"] = {"ok": True, "data": None}


class SSHResource:

    async def on_get(self, req: Request, resp: Response) -> None:
        """Получить список SSH ключей в контейнере"""
        logger.info(f"GET /ssh request from {req.remote_addr}")
        
        success, keys, error = list_ssh_keys_in_container()
        
        if success:
            keys_list = [k.strip() for k in keys.split("\n") if k.strip()] if keys else []
            logger.info(f"Retrieved {len(keys_list)} SSH keys")
            resp.status = falcon.HTTP_200
            resp.context["result"] = {"ok": True, "data": {"keys": keys_list}}
        else:
            logger.error(f"Failed to list SSH keys: {error}")
            resp.status = falcon.HTTP_500
            resp.context["result"] = {"ok": False, "error": error}

    async def on_post(self, req: Request, resp: Response) -> None:
        """Добавить SSH ключ в контейнер"""
        logger.info(f"POST /ssh request from {req.remote_addr}")
        
        try:
            json_data = req.context.get("json")
            if not json_data or "ssh_pubkey" not in json_data:
                logger.error("Missing ssh_pubkey in request")
                raise falcon.HTTPBadRequest(
                    title="Invalid request",
                    description="Missing 'ssh_pubkey' field"
                )
            
            ssh_pubkey = json_data["ssh_pubkey"]
            logger.info(f"Adding SSH key (length: {len(ssh_pubkey)} chars)")
            
            success, error = add_ssh_key_to_container(ssh_pubkey)
            
            if success:
                logger.info("SSH key added successfully")
                resp.status = falcon.HTTP_200
                resp.context["result"] = {"ok": True, "data": {"message": "SSH key added successfully"}}
            else:
                logger.error(f"Failed to add SSH key: {error}")
                resp.status = falcon.HTTP_500
                resp.context["result"] = {"ok": False, "error": error}
                
        except falcon.HTTPBadRequest:
            raise
        except Exception as e:
            logger.error(f"Unexpected error adding SSH key: {e}", exc=e)
            resp.status = falcon.HTTP_500
            resp.context["result"] = {"ok": False, "error": str(e)}

    async def on_delete(self, req: Request, resp: Response) -> None:
        """Удалить SSH ключ из контейнера"""
        logger.info(f"DELETE /ssh request from {req.remote_addr}")
        
        try:
            json_data = req.context.get("json")
            if not json_data or "ssh_pubkey" not in json_data:
                logger.error("Missing ssh_pubkey in request")
                raise falcon.HTTPBadRequest(
                    title="Invalid request",
                    description="Missing 'ssh_pubkey' field"
                )
            
            ssh_pubkey = json_data["ssh_pubkey"]
            logger.info(f"Removing SSH key (length: {len(ssh_pubkey)} chars)")
            
            success, error = remove_ssh_key_from_container(ssh_pubkey)
            
            if success:
                logger.info("SSH key removed successfully")
                resp.status = falcon.HTTP_200
                resp.context["result"] = {"ok": True, "data": {"message": "SSH key removed successfully"}}
            else:
                logger.error(f"Failed to remove SSH key: {error}")
                resp.status = falcon.HTTP_500
                resp.context["result"] = {"ok": False, "error": error}
                
        except falcon.HTTPBadRequest:
            raise
        except Exception as e:
            logger.error(f"Unexpected error removing SSH key: {e}", exc=e)
            resp.status = falcon.HTTP_500
            resp.context["result"] = {"ok": False, "error": str(e)}


class ManageInstancesResource:

    async def on_get(self, req: Request, resp: Response) -> None:
        logger.info(f"GET /instances request from {req.remote_addr}")
        
        state = state_manager.get_current_state()
        response_data = asdict(state)
        
        logger.info(f"Current instance state: status={state.status}, container_id={state.container_id}")

        if req.get_param_as_bool("logs") and state.container_id:
            logger.info(f"Fetching logs for container {state.container_id[:12]}")
            success, logs, err = instances.get_instance_logs(state.container_id)
            if success:
                response_data["logs"] = logs
                logger.info(f"Container logs retrieved successfully ({len(logs)} bytes)")
            else:
                response_data["logs_error"] = err
                logger.error(f"Failed to retrieve container logs: {err}")

        resp.status = falcon.HTTP_200
        resp.context["result"] = {"ok": True, "data": response_data}

    async def on_post(self, req: Request, resp: Response) -> None:
        logger.info(f"POST /instances request from {req.remote_addr}")

        # Валидация запроса
        try:
            json_data = req.context.get("json")
            logger.info(f"Received JSON data: {json_data}")
            
            create_params = from_json(CreateInstance, json_data)
            logger.info(f"Creating instance: image={create_params.image}:{create_params.image_tag}, "
                       f"cpu={create_params.env_variables.get('QUDATA_CPU_CORES', '1')}, "
                       f"ram={create_params.env_variables.get('QUDATA_MEMORY_GB', '2')}GB, "
                       f"gpu={create_params.env_variables.get('QUDATA_GPU_COUNT', '0')}, "
                       f"ports={list(create_params.ports.keys()) if create_params.ports else []}")
        except Exception as e:
            logger.error(f"Invalid JSON payload for instance creation: {e}", exc=e)
            raise falcon.HTTPBadRequest(
                title="Invalid JSON payload", description=str(e)
            )

        # Выделяем порты СРАЗУ, до фонового создания
        from src.utils.ports import get_free_port
        
        allocated_ports = {}
        try:
            # Выделяем порты из запроса
            for container_port, host_port_def in (create_params.ports or {}).items():
                if str(host_port_def).lower() == "auto":
                    host_port = str(get_free_port())
                    logger.info(f"  Allocated auto port: {container_port} -> {host_port}")
                else:
                    host_port = str(host_port_def)
                    logger.info(f"  Using specified port: {container_port} -> {host_port}")
                allocated_ports[container_port] = host_port
            
            # Если SSH включен и порт 22 не указан, выделяем порт для SSH
            if create_params.ssh_enabled and "22" not in (create_params.ports or {}):
                ssh_port = str(get_free_port())
                allocated_ports["22"] = ssh_port
                logger.info(f"  Allocated SSH port: 22 -> {ssh_port}")
            
            logger.info(f"✓ Ports allocated: {allocated_ports}")
            
        except Exception as e:
            logger.error(f"Failed to allocate ports: {e}", exc=e)
            raise falcon.HTTPInternalServerError(
                title="Port allocation failed",
                description=str(e)
            )

        # Асинхронное создание контейнера в фоновом потоке
        def create_instance_async():
            try:
                logger.info("Starting background instance creation...")
                # Передаём предвыделенные порты в функцию создания
                success, data, error = instances.create_new_instance(create_params, allocated_ports)
                
                if success:
                    logger.info(f"✓ Instance created successfully in background: {data.get('ports', {})}")
                    # Отправляем статистику после успешного создания
                    send_stats_async()
                else:
                    logger.error(f"✗ Background instance creation failed: {error}")
                    # Обновляем состояние на error
                    current_state = state_manager.get_current_state()
                    current_state.status = "error"
                    current_state.container_id = None
                    state_manager.save_state(current_state)
            except Exception as e:
                logger.error(f"✗ Unexpected error in background instance creation: {e}", exc=e)
                # Обновляем состояние на error
                current_state = state_manager.get_current_state()
                current_state.status = "error"
                current_state.container_id = None
                state_manager.save_state(current_state)
        
        # Запускаем создание в фоне
        Thread(target=create_instance_async, daemon=True).start()
        
        # Сразу возвращаем успех с выделенными портами (202 Accepted)
        logger.info(f"✓ Instance creation request accepted, ports allocated: {allocated_ports}")
        resp.status = falcon.HTTP_202  # 202 Accepted - запрос принят, обрабатывается
        resp.context["result"] = {
            "ok": True, 
            "data": {
                "message": "Instance creation started",
                "status": "creating",
                "ports": allocated_ports  # Возвращаем выделенные порты
            }
        }

    async def on_put(self, req: Request, resp: Response) -> None:
        logger.info(f"PUT /instances request from {req.remote_addr}")

        try:
            manage_params = from_json(ManageInstance, req.context.get("json"))
            action_value = manage_params.action.value if hasattr(manage_params.action, 'value') else str(manage_params.action)
            logger.info(f"Instance management action requested: {action_value}")
        except Exception as e:
            logger.error(f"Invalid JSON payload for instance management: {e}")
            raise falcon.HTTPBadRequest(
                title="Invalid JSON payload", description=str(e)
            )

        success, error = instances.manage_instance(manage_params)

        if success:
            logger.info(f"Instance action '{action_value}' completed successfully")
            send_stats_async()
            resp.status = falcon.HTTP_200
            resp.context["result"] = {"ok": True}
        else:
            logger.error(f"Instance action '{action_value}' failed: {error}")
            resp.status = falcon.HTTP_500
            resp.context["result"] = {"ok": False, "error": error}

    async def on_delete(self, req: Request, resp: Response) -> None:
        logger.info(f"DELETE /instances request from {req.remote_addr}")
        
        state = state_manager.get_current_state()
        container_id = state.container_id[:12] if state.container_id else "none"
        logger.info(f"Deleting instance: container_id={container_id}, status={state.status}")
        
        success, error = instances.delete_instance()
        
        if success:
            logger.info(f"Instance deleted successfully")
            resp.status = falcon.HTTP_200
            resp.context["result"] = {"ok": True}
        else:
            logger.error(f"Failed to delete instance: {error}")
            resp.status = falcon.HTTP_500
            resp.context["result"] = {"ok": False, "error": error}
