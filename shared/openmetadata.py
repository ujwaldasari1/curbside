"""Minimal OpenMetadata REST client (bot-JWT auth) shared by governance seeding, the
curbside MCP server and the agents. Deliberately thin: the `openmetadata-ingestion`
SDK lives in its own virtualenv because its pins conflict with dbt/Dagster."""

import os
from typing import Any
from urllib.parse import quote

import requests


class OpenMetadataError(RuntimeError):
    pass


class OpenMetadataClient:
    def __init__(self, host: str | None = None, token: str | None = None, timeout: int = 30):
        self.host = (host or os.environ.get("OPENMETADATA_HOST", "http://localhost:8585/api")).rstrip("/")
        token = token or os.environ.get("OPENMETADATA_JWT_TOKEN")
        if not token:
            raise OpenMetadataError("OPENMETADATA_JWT_TOKEN is not set (see .env.example)")
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> Any:
        response = self.session.request(method, f"{self.host}{path}", timeout=self.timeout, **kwargs)
        if response.status_code == 404:
            return None
        if not response.ok:
            raise OpenMetadataError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
        return response.json() if response.content else None

    def get(self, path: str, **params) -> Any:
        return self._request("GET", path, params=params or None)

    def put(self, path: str, body: dict) -> Any:
        return self._request("PUT", path, json=body)

    def post(self, path: str, body: Any) -> Any:
        return self._request("POST", path, json=body)

    def patch(self, path: str, operations: list[dict]) -> Any:
        return self._request(
            "PATCH", path, json=operations, headers={"Content-Type": "application/json-patch+json"}
        )

    # -- convenience -------------------------------------------------------------------
    def get_by_name(self, entity_path: str, fqn: str, fields: str | None = None) -> dict | None:
        """e.g. get_by_name('tables', 'curbside_warehouse.curbside.marts.fct_monthly_tonnage')."""
        params = {"fields": fields} if fields else {}
        return self.get(f"/v1/{entity_path}/name/{quote(fqn, safe='')}", **params)

    def search(self, query: str, index: str = "table_search_index", size: int = 10) -> list[dict]:
        result = self.get("/v1/search/query", q=query, index=index, size=size)
        return [hit["_source"] for hit in (result or {}).get("hits", {}).get("hits", [])]
