import sys
from typing import Any, Dict, Optional

import httpx

from src import consts
from src.storage.secure import get_agent_secret


class HttpClient:

    def __init__(self, base_url: str = consts.API_BASE_URL):
        # Упрощённый HTTP клиент с коротким таймаутом
        self._client = httpx.Client(
            base_url=base_url, 
            timeout=15.0,  # 15 секунд вместо 30
            follow_redirects=True
        )
        secret = get_agent_secret()
        api_key = sys.argv[1] if len(sys.argv) > 1 else ""
        self._client.headers.update({"X-Api-Key": api_key})
        if secret:
            self._client.headers.update({consts.APP_HEADER_NAME: secret})
        
        print(f"HttpClient initialized with base_url: {base_url}")
        print(f"API Key (first 8 chars): {api_key[:8] if api_key else 'NONE'}")

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Упрощённый запрос без backoff ретраев"""
        print(f"HTTP {method} {path}")
        try:
            response = self._client.request(method, path, json=json, params=params)
            print(f"Response status: {response.status_code}")
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as e:
            print(f"✗ Request timeout after 15 seconds")
            raise
        except httpx.HTTPStatusError as e:
            print(f"✗ HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            raise
        except Exception as e:
            print(f"✗ Request error: {type(e).__name__}: {e}")
            raise

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
