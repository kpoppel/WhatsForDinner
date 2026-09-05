"""Typed transport boundary for the subset of Tandoor APIs used by the app.

One lazy ``httpx.AsyncClient`` is reused for connection pooling and closed by
the FastAPI lifespan. Requests are not retried here because writes do not have
a general upstream idempotency contract.
"""

from __future__ import annotations

from typing import Any

import httpx
import logging
from time import perf_counter

from app.config import settings


class TandoorError(RuntimeError):
    """Raised when Tandoor cannot be reached or returns an error."""


class TandoorClient:
    """Send authenticated Tandoor requests and normalize transport failures."""

    def __init__(self) -> None:
        self.base_url = settings.tandoor_base_url.rstrip("/")
        self.timeout = settings.tandoor_timeout_seconds
        self.api_token = settings.tandoor_api_token
        self._http_client: httpx.AsyncClient | None = None

    async def close(self) -> None:
        """Close the shared HTTP client during application shutdown."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _client(self) -> httpx.AsyncClient:
        """Lazily create and then reuse the pooled upstream HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._http_client

    def _headers(self) -> dict[str, str]:
        """Build authenticated JSON headers without exposing the token value."""
        headers = {"Accept": "application/json"}
        if self.api_token:
            token = self.api_token.strip()
            # Tandoor API expects: Authorization: Bearer TOKEN
            if token.lower().startswith("bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _record_timing(self, method: str, path: str, started_at: float, status: object, error: Exception | None = None) -> None:
        """Emit optional upstream timing telemetry without affecting requests."""
        if not settings.performance_metrics_enabled:
            return
        logging.getLogger("wfd.tandoor").info(
            "event=tandoor_timing method=%s path=%s duration_ms=%.3f status=%s error=%s",
            method,
            path,
            (perf_counter() - started_at) * 1000,
            status,
            str(error) if error else "",
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Execute one upstream request and normalize HTTP failures to TandoorError."""
        url = f"{self.base_url}{path}"
        started_at = perf_counter()
        status: object = "exception"
        try:
            response = await self._client().request(
                method=method,
                url=url,
                params=params,
                json=json,
                headers=self._headers(),
            )
            status = response.status_code
            response.raise_for_status()
            if response.content:
                self._record_timing(method, path, started_at, status)
                return response.json()
            self._record_timing(method, path, started_at, status)
            return {"status": "ok"}
        except httpx.HTTPStatusError as exc:
            self._record_timing(method, path, started_at, exc.response.status_code, exc)
            body = exc.response.text.strip()
            body_snippet = body[:300] if body else ""
            raise TandoorError(
                f"Tandoor returned {exc.response.status_code} for {path}."
                + (f" Response: {body_snippet}" if body_snippet else "")
            ) from exc
        except httpx.HTTPError as exc:
            self._record_timing(method, path, started_at, status, exc)
            raise TandoorError(f"Unable to reach Tandoor at {self.base_url}.") from exc

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue a GET through the shared request/error-normalization path."""
        return await self._request("GET", path, params=params)

    async def list_recipes(
        self,
        search: str | None = None,
        limit: int = 20,
        page: int | None = None,
        keyword_ids: list[int] | None = None,
    ) -> Any:
        """List recipes using Tandoor pagination, search, and keyword filters."""
        params: dict[str, Any] = {"page_size": limit}
        if page is not None:
            params["page"] = page
        if search:
            params["query"] = search
        if keyword_ids:
            params["keywords"] = keyword_ids
        return await self._get("/api/recipe/", params=params)

    async def get_recipe(self, recipe_id: int) -> Any:
        """Fetch one complete recipe payload from Tandoor."""
        return await self._get(f"/api/recipe/{recipe_id}/")

    async def list_tags(self) -> Any:
        """Fetch the keyword catalog used by recipe filtering."""
        return await self._get("/api/keyword/")

    async def list_meal_types(self, limit: int = 50) -> Any:
        """Fetch available upstream meal types for generated plans."""
        return await self._get("/api/meal-type/", params={"page_size": limit})

    @staticmethod
    def normalize_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
        """Convert variant Tandoor recipe shapes into the app's stable recipe contract."""
        ingredients: list[dict[str, Any]] = []

        # Some Tandoor payloads expose ingredients under steps[].ingredients.
        step_items = []
        for step in recipe.get("steps", []):
            if isinstance(step, dict):
                step_ingredients = step.get("ingredients")
                if isinstance(step_ingredients, list):
                    step_items.extend(step_ingredients)

        top_level_items = recipe.get("ingredients", [])
        source_items = step_items if step_items else top_level_items

        for item in source_items:
            if not isinstance(item, dict):
                continue

            food = item.get("food")
            ingredient_obj = item.get("ingredient")
            unit_obj = item.get("unit")

            name = ""
            if isinstance(food, dict):
                name = food.get("name") or ""
            elif isinstance(ingredient_obj, dict):
                name = ingredient_obj.get("name") or ingredient_obj.get("title") or ""
            else:
                name = item.get("name") or ""

            unit_name: Any = unit_obj.get("name") if isinstance(unit_obj, dict) else unit_obj

            ingredients.append(
                {
                    "name": name,
                    "amount": item.get("amount"),
                    "unit": unit_name,
                }
            )

        steps: list[dict[str, Any]] = []
        for step in recipe.get("steps", []):
            if isinstance(step, dict):
                steps.append(
                    {
                        "instruction": (
                            step.get("instruction")
                            or step.get("text")
                            or step.get("name")
                            or ""
                        ),
                    }
                )

        return {
            "id": recipe.get("id"),
            "title": recipe.get("name") or recipe.get("title") or "Untitled recipe",
            "ingredients": ingredients,
            "steps": steps,
        }

    async def list_meal_plans(self, limit: int = 50) -> Any:
        """List upstream meal-plan rows for reconciliation."""
        return await self._get("/api/meal-plan/", params={"page_size": limit})

    async def create_meal_plan(self, payload: dict[str, Any]) -> Any:
        """Create one upstream meal-plan row."""
        return await self._request("POST", "/api/meal-plan/", json=payload)

    async def update_meal_plan(self, meal_id: int, payload: dict[str, Any]) -> Any:
        """Patch one upstream meal-plan row by its Tandoor ID."""
        return await self._request("PATCH", f"/api/meal-plan/{meal_id}/", json=payload)

    async def delete_meal_plan(self, meal_id: int) -> Any:
        """Delete one upstream meal-plan row."""
        return await self._request("DELETE", f"/api/meal-plan/{meal_id}/")

    async def list_shopping_entries(self, limit: int = 100) -> Any:
        """List upstream shopping entries for canonical hydration."""
        return await self._get("/api/shopping-list-entry/", params={"page_size": limit})

    async def create_shopping_entry(self, payload: dict[str, Any]) -> Any:
        """Create one upstream shopping entry."""
        return await self._request("POST", "/api/shopping-list-entry/", json=payload)

    async def update_shopping_entry(self, entry_id: int, payload: dict[str, Any]) -> Any:
        """Patch one upstream shopping entry by ID."""
        return await self._request(
            "PATCH", f"/api/shopping-list-entry/{entry_id}/", json=payload
        )

    async def delete_shopping_entry(self, entry_id: int) -> Any:
        """Delete one upstream shopping entry by ID."""
        return await self._request("DELETE", f"/api/shopping-list-entry/{entry_id}/")

    async def create_shopping_list_from_recipe(self, payload: dict[str, Any]) -> Any:
        """Activate a recipe in Tandoor's shopping-list workflow."""
        return await self._request("POST", "/api/shopping-list-recipe/", json=payload)

    async def bulk_create_shopping_list_recipe_entries(
        self,
        shopping_recipe_id: int,
        payload: dict[str, Any],
    ) -> Any:
        """Bulk-create shopping entries for an activated recipe."""
        return await self._request(
            "POST",
            f"/api/shopping-list-recipe/{shopping_recipe_id}/bulk_create_entries/",
            json=payload,
        )
