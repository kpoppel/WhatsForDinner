from __future__ import annotations

import random
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

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    headers=self._headers(),
                )
                response.raise_for_status()
                if response.content:
                    return response.json()
                return {"status": "ok"}
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()
            body_snippet = body[:300] if body else ""
            raise TandoorError(
                f"Tandoor returned {exc.response.status_code} for {path}."
                + (f" Response: {body_snippet}" if body_snippet else "")
            ) from exc
        except httpx.HTTPError as exc:
            raise TandoorError(f"Unable to reach Tandoor at {self.base_url}.") from exc

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def list_recipes(
        self,
        search: str | None = None,
        limit: int = 20,
        page: int | None = None,
        keyword_ids: list[int] | None = None,
    ) -> Any:
        params: dict[str, Any] = {"page_size": limit}
        if page is not None:
            params["page"] = page
        if search:
            params["query"] = search
        if keyword_ids:
            params["keywords"] = keyword_ids
        return await self._get("/api/recipe/", params=params)

    async def list_recipes_all(
        self,
        search: str | None = None,
        keyword_ids: list[int] | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        all_results: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None

        while True:
            data = await self.list_recipes(
                search=search,
                limit=page_size,
                page=page,
                keyword_ids=keyword_ids,
            )

            if not isinstance(data, dict):
                # Fall back to the original payload if pagination metadata is absent.
                return {"count": 0, "next": None, "previous": None, "results": []}

            if total_count is None and isinstance(data.get("count"), int):
                total_count = int(data["count"])

            batch = data.get("results")
            if not isinstance(batch, list):
                break

            all_results.extend([row for row in batch if isinstance(row, dict)])

            next_page = data.get("next")
            if not next_page or not batch:
                break

            page += 1

        return {
            "count": total_count if total_count is not None else len(all_results),
            "next": None,
            "previous": None,
            "results": all_results,
        }

    async def get_recipe(self, recipe_id: int) -> Any:
        return await self._get(f"/api/recipe/{recipe_id}/")

    async def random_recipe_by_keywords(
        self, keyword_ids: list[int], sample_size: int = 100
    ) -> dict[str, Any] | None:
        data = await self.list_recipes(limit=sample_size, keyword_ids=keyword_ids)
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            return None
        chosen = random.choice(results)
        chosen_id = chosen.get("id") if isinstance(chosen, dict) else None
        if not isinstance(chosen_id, int):
            return None
        return await self.get_recipe(chosen_id)

    async def list_tags(self) -> Any:
        return await self._get("/api/keyword/")

    async def list_meal_types(self, limit: int = 50) -> Any:
        return await self._get("/api/meal-type/", params={"page_size": limit})

    @staticmethod
    def normalize_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
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

    async def shopping_list(self) -> Any:
        return await self._get("/api/shopping-list/")

    async def list_meal_plans(self, limit: int = 50) -> Any:
        return await self._get("/api/meal-plan/", params={"page_size": limit})

    async def create_meal_plan(self, payload: dict[str, Any]) -> Any:
        return await self._request("POST", "/api/meal-plan/", json=payload)

    async def update_meal_plan(self, meal_id: int, payload: dict[str, Any]) -> Any:
        return await self._request("PATCH", f"/api/meal-plan/{meal_id}/", json=payload)

    async def delete_meal_plan(self, meal_id: int) -> Any:
        return await self._request("DELETE", f"/api/meal-plan/{meal_id}/")

    async def list_shopping_entries(self, limit: int = 100) -> Any:
        return await self._get("/api/shopping-list-entry/", params={"page_size": limit})

    async def create_shopping_entry(self, payload: dict[str, Any]) -> Any:
        return await self._request("POST", "/api/shopping-list-entry/", json=payload)

    async def update_shopping_entry(self, entry_id: int, payload: dict[str, Any]) -> Any:
        return await self._request(
            "PATCH", f"/api/shopping-list-entry/{entry_id}/", json=payload
        )

    async def delete_shopping_entry(self, entry_id: int) -> Any:
        return await self._request("DELETE", f"/api/shopping-list-entry/{entry_id}/")

    async def create_shopping_list_from_recipe(self, payload: dict[str, Any]) -> Any:
        return await self._request("POST", "/api/shopping-list-recipe/", json=payload)

    async def update_recipe_shopping(self, recipe_id: int, payload: dict[str, Any]) -> Any:
        return await self._request("PUT", f"/api/recipe/{recipe_id}/shopping/", json=payload)
