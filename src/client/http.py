import sys
from typing import Any, Dict, Optional

import backoff
import httpx

from src import consts
from src.storage.secure import get_agent_secret


class HttpClient:

    def __init__(self, base_url: str = consts.API_BASE_URL):
        self._client = httpx.Client(base_url=base_url, timeout=30.0)
        secret = get_agent_secret()
        api_key = sys.argv[1] if len(sys.argv) > 1 else ""
        self._client.headers.update({"X-Api-Key": api_key})
        if secret:
            self._client.headers.update({consts.APP_HEADER_NAME: secret})

    @backoff.on_exception(backoff.expo, httpx.HTTPError, max_time=60, max_tries=5)
    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = self._client.request(method, path, json=json, params=params)
        response.raise_for_status()
        return response.json()

    def update_secret(self, secret: str) -> None:
        self._client.headers.update({consts.APP_HEADER_NAME: secret})

    def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._request("POST", path, json=json, params=params)
