from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException

from app.config import settings
from app.services.stage2_state import Stage2State
from app.services.tandoor_client import TandoorClient, TandoorError


class MealPlanService:
    def __init__(self, state: Stage2State, tandoor_client: TandoorClient) -> None:
        self._state = state
        self._client = tandoor_client

    def _parse_constraint_days(self, days: list[Any], start_date: date, length_days: int) -> set[int]:
        indexes: set[int] = set()
        for item in days:
            if isinstance(item, int):
                idx = item - 1 if item > 0 else item
                if 0 <= idx < length_days:
                    indexes.add(idx)
                continue

            if isinstance(item, str):
                try:
                    target_date = date.fromisoformat(item)
                except ValueError:
                    continue
                idx = (target_date - start_date).days
                if 0 <= idx < length_days:
                    indexes.add(idx)
        return indexes

    def _recipe_url(self, recipe_id: int | None) -> str | None:
        if recipe_id is None:
            return None
        return f"{settings.tandoor_base_url.rstrip('/')}/recipe/{recipe_id}"

    def _recipe_title(self, recipe: dict[str, Any]) -> str:
        return str(recipe.get("name") or recipe.get("title") or f"Recipe {recipe.get('id')}")

    def _extract_results(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                return [row for row in results if isinstance(row, dict)]
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    def _extract_recipe_ingredient_ids(self, recipe_payload: dict[str, Any]) -> list[int]:
        ids: list[int] = []
        steps = recipe_payload.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_ingredients = step.get("ingredients")
                if not isinstance(step_ingredients, list):
                    continue
                for ingredient in step_ingredients:
                    if not isinstance(ingredient, dict):
                        continue
                    ingredient_id = ingredient.get("id")
                    if isinstance(ingredient_id, int):
                        ids.append(ingredient_id)

        top_ingredients = recipe_payload.get("ingredients")
        if isinstance(top_ingredients, list):
            for ingredient in top_ingredients:
                if not isinstance(ingredient, dict):
                    continue
                ingredient_id = ingredient.get("id")
                if isinstance(ingredient_id, int):
                    ids.append(ingredient_id)

        return sorted(set(ids))

    def _collect_recipe_history_dates(self) -> dict[int, list[date]]:
        history: dict[int, list[date]] = {}
        for plan in self._state.list_meal_plans():
            entries = plan.get("entries")
            if not isinstance(entries, list):
                continue

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                recipe = entry.get("recipe")
                if not isinstance(recipe, dict):
                    continue
                recipe_id = recipe.get("id")
                if not isinstance(recipe_id, int):
                    continue
                date_value = entry.get("date")
                if not isinstance(date_value, str):
                    continue
                try:
                    entry_date = date.fromisoformat(date_value)
                except ValueError:
                    continue

                history.setdefault(recipe_id, []).append(entry_date)

        for recipe_id, dates in history.items():
            dates.sort()
            history[recipe_id] = dates
        return history

    def _is_within_no_repeat_window(
        self,
        recipe_id: int,
        candidate_date: date,
        no_repeat_days: int,
        history_dates: dict[int, list[date]],
    ) -> bool:
        if no_repeat_days <= 0:
            return False

        for seen_date in history_dates.get(recipe_id, []):
            if seen_date >= candidate_date:
                break
            if (candidate_date - seen_date).days <= no_repeat_days:
                return True
        return False

    def _next_plan_entry_id(self) -> int:
        return self._state.allocate_entry_id()

    def _find_entry(self, plan: dict[str, Any], entry_id: int) -> dict[str, Any] | None:
        entries = plan.get("entries", [])
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if isinstance(entry, dict) and entry.get("entry_id") == entry_id:
                return entry
        return None

    def _normalize_plan_entries(self, entries: list[dict[str, Any]], plan_start_date: Any) -> list[dict[str, Any]]:
        start_day: date | None
        try:
            start_day = date.fromisoformat(str(plan_start_date))
        except ValueError:
            start_day = None

        normalized = [row for row in entries if isinstance(row, dict)]
        normalized.sort(key=lambda row: int(row.get("day_index", 0)))
        for idx, row in enumerate(normalized):
            row["day_index"] = idx
            if start_day is not None:
                row["date"] = (start_day + timedelta(days=idx)).isoformat()
        return normalized

    def _enrich_plan_recipe_urls(self, plan: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(plan, dict):
            return plan
        enriched = dict(plan)
        entries = plan.get("entries")
        if not isinstance(entries, list):
            return enriched

        enriched_entries: list[Any] = []
        for entry in entries:
            if not isinstance(entry, dict):
                enriched_entries.append(entry)
                continue
            enriched_entry = dict(entry)
            recipe = entry.get("recipe")
            if isinstance(recipe, dict):
                enriched_recipe = dict(recipe)
                recipe_id = recipe.get("id")
                enriched_recipe["url"] = self._recipe_url(recipe_id) if isinstance(recipe_id, int) else None
                enriched_entry["recipe"] = enriched_recipe
            enriched_entries.append(enriched_entry)

        enriched["entries"] = enriched_entries
        return enriched

    async def generate_plan(
        self,
        *,
        start_day: date,
        length_days: int,
        diners: int,
        constraints: dict[str, list[int | str]],
        keyword_ids: list[int],
        no_repeat_days: int,
    ) -> dict:
        leftover_days = self._parse_constraint_days(constraints.get("leftover_days", []), start_day, length_days)
        takeout_days = self._parse_constraint_days(constraints.get("takeout_days", []), start_day, length_days)
        empty_days = self._parse_constraint_days(constraints.get("empty_days", []), start_day, length_days)

        recipe_candidates: list[dict[str, Any]] = []
        try:
            result = await self._client.list_recipes(
                limit=max(20, length_days * 3),
                keyword_ids=keyword_ids if len(keyword_ids) > 0 else None,
            )
            recipe_candidates = self._extract_results(result)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        recipe_history_dates = self._collect_recipe_history_dates()

        recipe_pointer = 0
        randomized_candidates = recipe_candidates[:]
        if len(randomized_candidates) > 0:
            random.SystemRandom().shuffle(randomized_candidates)
        entries: list[dict[str, Any]] = []
        last_recipe: dict[str, Any] | None = None

        for day_index in range(length_days):
            entry_date = start_day + timedelta(days=day_index)
            mode = "planned"
            recipe_obj: dict[str, Any] | None = None

            if day_index in empty_days:
                mode = "empty"
            elif day_index in takeout_days:
                mode = "takeout"
            elif day_index in leftover_days and last_recipe is not None:
                mode = "leftover"
                recipe_obj = last_recipe
            elif len(randomized_candidates) > 0:
                if recipe_pointer > 0 and recipe_pointer % len(randomized_candidates) == 0:
                    random.SystemRandom().shuffle(randomized_candidates)

                chosen_obj: dict[str, Any] | None = None
                candidate_len = len(randomized_candidates)

                for offset in range(candidate_len):
                    candidate = randomized_candidates[(recipe_pointer + offset) % candidate_len]
                    candidate_id = candidate.get("id") if isinstance(candidate, dict) else None
                    if not isinstance(candidate_id, int):
                        continue
                    if self._is_within_no_repeat_window(
                        recipe_id=candidate_id,
                        candidate_date=entry_date,
                        no_repeat_days=no_repeat_days,
                        history_dates=recipe_history_dates,
                    ):
                        continue
                    chosen_obj = candidate
                    recipe_pointer += offset + 1
                    break

                if chosen_obj is not None:
                    chosen_id = chosen_obj.get("id")
                    if isinstance(chosen_id, int):
                        recipe_history_dates.setdefault(chosen_id, []).append(entry_date)
                        recipe_history_dates[chosen_id].sort()

                    recipe_obj = {
                        "id": chosen_id,
                        "title": self._recipe_title(chosen_obj),
                        "url": self._recipe_url(chosen_id),
                    }
                    last_recipe = recipe_obj

            entries.append(
                {
                    "entry_id": self._next_plan_entry_id(),
                    "day_index": day_index,
                    "date": entry_date.isoformat(),
                    "mode": mode,
                    "recipe": recipe_obj,
                    "servings": diners,
                    "reminder_enabled": False,
                    "reminder_text": "",
                    "notes": "",
                }
            )

        plan_payload = {
            "start_date": start_day.isoformat(),
            "length_days": length_days,
            "diners": diners,
            "no_repeat_days": no_repeat_days,
            "keyword_ids": keyword_ids,
            "constraints": {
                "leftover_days": sorted(leftover_days),
                "takeout_days": sorted(takeout_days),
                "empty_days": sorted(empty_days),
            },
            "entries": entries,
        }

        stored = self._state.create_meal_plan(plan_payload)
        self._state.append_sync_event("meal_plan_generated", stored)
        return {"source": "tandoor+local-state", "data": self._enrich_plan_recipe_urls(stored)}

    async def patch_plan(self, plan_id: int, payload: dict[str, Any]) -> dict:
        current = self._state.get_meal_plan(plan_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        mutable: dict[str, Any] = {}
        start_date_override: str | None = None
        if "start_date" in payload:
            raw_start_date = payload.get("start_date")
            if not isinstance(raw_start_date, str):
                raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD.")
            try:
                parsed_start = date.fromisoformat(raw_start_date)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD.") from exc
            start_date_override = parsed_start.isoformat()
            mutable["start_date"] = start_date_override

        for key in ("start_date", "length_days", "diners", "constraints", "keyword_ids"):
            if key in payload and key != "start_date":
                mutable[key] = payload[key]

        if "entries" in payload and isinstance(payload["entries"], list):
            mutable["entries"] = payload["entries"]

        if start_date_override is not None:
            entries_source = mutable.get("entries")
            if not isinstance(entries_source, list):
                current_entries = current.get("entries")
                entries_source = current_entries if isinstance(current_entries, list) else []

            normalized_entries = self._normalize_plan_entries(entries_source, start_date_override)
            mutable["entries"] = normalized_entries
            if "length_days" not in mutable:
                mutable["length_days"] = len(normalized_entries)

        updated = self._state.update_meal_plan(plan_id, mutable)
        if updated is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        self._state.append_sync_event("meal_plan_updated", {"plan_id": plan_id, "payload": payload})
        return {"source": "local-state", "data": self._enrich_plan_recipe_urls(updated)}

    async def add_entry(self, plan_id: int, payload: dict[str, Any]) -> dict:
        plan = self._state.get_meal_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        entries = plan.get("entries")
        if not isinstance(entries, list):
            entries = []

        day_index = int(payload.get("day_index") if payload.get("day_index") is not None else len(entries))
        entry_date = payload.get("date")
        if not isinstance(entry_date, str):
            try:
                start_day = date.fromisoformat(str(plan.get("start_date")))
            except ValueError:
                start_day = date.today()
            entry_date = (start_day + timedelta(days=day_index)).isoformat()

        mode = str(payload.get("mode") or "planned")
        recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else None

        entry = {
            "entry_id": self._next_plan_entry_id(),
            "day_index": day_index,
            "date": entry_date,
            "mode": mode,
            "recipe": recipe,
            "servings": int(payload.get("servings") or plan.get("diners") or 2),
            "reminder_enabled": bool(payload.get("reminder_enabled", False)),
            "reminder_text": str(payload.get("reminder_text") or ""),
            "notes": str(payload.get("notes") or ""),
        }

        entries.append(entry)
        entries = self._normalize_plan_entries(entries, plan.get("start_date"))

        updated = self._state.update_meal_plan(
            plan_id,
            {
                "entries": entries,
                "length_days": len(entries),
            },
        )
        self._state.append_sync_event("meal_plan_entry_added", {"plan_id": plan_id, "entry": entry})

        return {"source": "local-state", "data": self._enrich_plan_recipe_urls(updated)}

    async def patch_entry(self, plan_id: int, entry_id: int, payload: dict[str, Any]) -> dict:
        plan = self._state.get_meal_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        entry = self._find_entry(plan, entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Meal plan entry not found.")

        for key in (
            "day_index",
            "date",
            "mode",
            "recipe",
            "servings",
            "reminder_enabled",
            "reminder_text",
            "notes",
        ):
            if key in payload:
                entry[key] = payload[key]

        target_day_index = payload.get("target_day_index")
        if target_day_index is not None:
            entries_for_reorder = plan.get("entries")
            if not isinstance(entries_for_reorder, list):
                raise HTTPException(status_code=404, detail="Meal plan entry not found.")

            ordered_entries = [row for row in entries_for_reorder if isinstance(row, dict)]
            ordered_entries.sort(key=lambda row: int(row.get("day_index", 0)))

            from_index = -1
            for idx, row in enumerate(ordered_entries):
                if int(row.get("entry_id", -1)) == entry_id:
                    from_index = idx
                    break

            if from_index < 0:
                raise HTTPException(status_code=404, detail="Meal plan entry not found.")

            moved_entry = ordered_entries.pop(from_index)

            target_index = int(target_day_index)
            if target_index < 0:
                target_index = 0
            if target_index > len(ordered_entries):
                target_index = len(ordered_entries)

            ordered_entries.insert(target_index, moved_entry)

            start_day: date | None
            try:
                start_day = date.fromisoformat(str(plan.get("start_date")))
            except ValueError:
                start_day = None

            for idx, row in enumerate(ordered_entries):
                row["day_index"] = idx
                if start_day is not None:
                    row["date"] = (start_day + timedelta(days=idx)).isoformat()

            plan["entries"] = ordered_entries

        entries = plan.get("entries", [])
        if isinstance(entries, list):
            entries.sort(key=lambda row: int(row.get("day_index", 0)))

        updated = self._state.update_meal_plan(plan_id, {"entries": entries})
        self._state.append_sync_event(
            "meal_plan_entry_updated",
            {"plan_id": plan_id, "entry_id": entry_id, "payload": payload},
        )

        return {"source": "local-state", "data": self._enrich_plan_recipe_urls(updated)}

    async def delete_entry(self, plan_id: int, entry_id: int) -> dict:
        plan = self._state.get_meal_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        entries = plan.get("entries")
        if not isinstance(entries, list):
            raise HTTPException(status_code=404, detail="Meal plan entry not found.")

        before = len(entries)
        entries = [row for row in entries if int(row.get("entry_id", -1)) != entry_id]
        if len(entries) == before:
            raise HTTPException(status_code=404, detail="Meal plan entry not found.")

        entries = self._normalize_plan_entries(entries, plan.get("start_date"))
        updated = self._state.update_meal_plan(
            plan_id,
            {
                "entries": entries,
                "length_days": len(entries),
            },
        )
        self._state.append_sync_event("meal_plan_entry_deleted", {"plan_id": plan_id, "entry_id": entry_id})

        return {"source": "local-state", "data": updated}

    async def generate_shopping_from_plan(
        self,
        *,
        plan_id: int,
        ensure_tandoor_writes_enabled,
        build_shopping_view,
    ) -> dict:
        ensure_tandoor_writes_enabled("meal_plan_to_shopping_list")
        plan = self._state.get_meal_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        entries = plan.get("entries")
        if not isinstance(entries, list):
            entries = []

        created: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for entry in entries:
            recipe = entry.get("recipe") if isinstance(entry, dict) else None
            if not isinstance(recipe, dict):
                continue

            recipe_id = recipe.get("id")
            if not isinstance(recipe_id, int):
                continue

            servings = int(entry.get("servings") or plan.get("diners") or 2)
            try:
                recipe_payload = await self._client.get_recipe(recipe_id)
                ingredient_ids = self._extract_recipe_ingredient_ids(recipe_payload)
                request_payload = {"ingredients": ingredient_ids, "servings": servings}
                result = await self._client.update_recipe_shopping(recipe_id, request_payload)
                created.append(
                    {
                        "entry_id": entry.get("entry_id"),
                        "operation": "recipe_shopping_update",
                        "payload": request_payload,
                        "result": result,
                    }
                )
            except TandoorError as exc:
                failed.append(
                    {
                        "entry_id": entry.get("entry_id"),
                        "operation": "recipe_shopping_update",
                        "payload": {"ingredients": [], "servings": servings},
                        "errors": [str(exc)],
                    }
                )

        sync_payload = {
            "plan_id": plan_id,
            "created_count": len(created),
            "failed_count": len(failed),
        }
        self._state.append_sync_event("meal_plan_shopping_generated", sync_payload)

        shopping_view: dict[str, Any] | None = None
        shopping_view_error: str | None = None
        try:
            shopping_entries = await self._client.list_shopping_entries(limit=500)
            shopping_view = build_shopping_view(self._extract_results(shopping_entries))
        except TandoorError as exc:
            shopping_view_error = str(exc)

        return {
            "source": "tandoor+local-state",
            "data": {
                "plan_id": plan_id,
                "created": created,
                "failed": failed,
                "shopping_view": shopping_view,
                "shopping_view_error": shopping_view_error,
            },
        }
