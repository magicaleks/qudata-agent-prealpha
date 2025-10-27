from src.client.http import HttpClient
from src.client.models import AgentResponse, CreateHost, InitAgent, Stats
from src.storage.secure import set_agent_secret
from src.utils.dto import from_json, to_json


class QudataClient:

    def __init__(self, http_client: HttpClient = HttpClient()):
        self._client = http_client

    def ping(self) -> bool:
        resp = self._client.get("/ping")
        return resp.get("ok", False)

    def init(self, data: InitAgent) -> AgentResponse:
        resp = self._client.post("/init", json=to_json(data))
        agent = from_json(AgentResponse, resp["data"])
        if agent.secret_key:
            set_agent_secret(agent.secret_key)
            self._client.update_secret(agent.secret_key)
        return agent

    def create_host(self, data: CreateHost) -> None:
        self._client.post("/init/host", json=to_json(data))

    def send_stats(self, data: Stats) -> None:
        self._client.post("/stats", json=to_json(data))
