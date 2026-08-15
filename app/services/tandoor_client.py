from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class TandoorError(RuntimeError):
    """Raised when Tandoor cannot be reached or returns an error."""


class TandoorClient:
    def __init__(self) -> None:
        self.base_url = settings.tandoor_base_url.rstrip("/")
        self.timeout = settings.tandoor_timeout_seconds
        self.api_token = settings.tandoor_api_token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            token = self.api_token.strip()
            # Tandoor API expects: Authorization: Bearer TOKEN
            if token.lower().startswith("bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params, headers=self._headers())
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            raise TandoorError(
                f"Tandoor returned {exc.response.status_code} for {path}."
            ) from exc
        except httpx.HTTPError as exc:
            raise TandoorError(f"Unable to reach Tandoor at {self.base_url}.") from exc

    async def list_recipes(self, search: str | None = None, limit: int = 20) -> Any:
        params: dict[str, Any] = {"page_size": limit}
        if search:
            params["query"] = search
        return await self._get("/api/recipe/", params=params)

    async def shopping_list(self) -> Any:
        return await self._get("/api/shopping-list/")
