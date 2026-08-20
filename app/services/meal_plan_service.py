from __future__ import annotations

import asyncio
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
        self._shopping_generation_locks: dict[int, asyncio.Lock] = {}

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

    def _instance_key_for_recipe(
        self,
        *,
        entry_id: int,
        role: str,
        recipe_id: int,
        slot_index: int | None,
    ) -> str:
        if role == "extra" and isinstance(slot_index, int):
            return f"entry:{entry_id}:extra:{slot_index}:recipe:{recipe_id}"
        return f"entry:{entry_id}:primary:recipe:{recipe_id}"

    def _desired_instance_sync(self, plan_payload: dict[str, Any], plan_entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        desired: dict[str, dict[str, Any]] = {}
        raw_diners = plan_payload.get("diners")
        default_servings = int(raw_diners) if isinstance(raw_diners, int) and raw_diners > 0 else 2

        for entry in plan_entries:
            if not isinstance(entry, dict):
                continue

            entry_id = entry.get("entry_id")
            if not isinstance(entry_id, int):
                continue

            raw_servings = entry.get("servings")
            servings = int(raw_servings) if isinstance(raw_servings, int) and raw_servings > 0 else default_servings

            entry_date = entry.get("date")
            entry_date_text = str(entry_date) if isinstance(entry_date, str) else ""

            primary_recipe = entry.get("recipe")
            if isinstance(primary_recipe, dict):
                recipe_id = primary_recipe.get("id")
                if isinstance(recipe_id, int):
                    key = self._instance_key_for_recipe(
                        entry_id=entry_id,
                        role="primary",
                        recipe_id=recipe_id,
                        slot_index=None,
                    )
                    desired[key] = {
                        "instance_key": key,
                        "entry_id": entry_id,
                        "recipe_id": recipe_id,
                        "role": "primary",
                        "slot_index": None,
                        "purpose": "meal",
                        "date": entry_date_text,
                        "servings": servings,
                        "entry_ids": set(),
                        "meal_plan_row_id": None,
                    }

            extra_recipes = entry.get("extra_recipes")
            if not isinstance(extra_recipes, list):
                continue

            for idx, extra_recipe in enumerate(extra_recipes):
                if not isinstance(extra_recipe, dict):
                    continue
                recipe = extra_recipe.get("recipe")
                if not isinstance(recipe, dict):
                    continue
                recipe_id = recipe.get("id")
                if not isinstance(recipe_id, int):
                    continue
                purpose = extra_recipe.get("purpose")
                key = self._instance_key_for_recipe(
                    entry_id=entry_id,
                    role="extra",
                    recipe_id=recipe_id,
                    slot_index=idx,
                )
                desired[key] = {
                    "instance_key": key,
                    "entry_id": entry_id,
                    "recipe_id": recipe_id,
                    "role": "extra",
                    "slot_index": idx,
                    "purpose": str(purpose) if purpose is not None else "extra",
                    "date": entry_date_text,
                    "servings": servings,
                    "entry_ids": set(),
                    "meal_plan_row_id": None,
                }

        return desired

    def _instance_key_for_mode(self, *, entry_id: int, mode: str) -> str:
        return f"entry:{entry_id}:mode:{mode}"

    def _desired_meal_plan_row_sync(
        self,
        plan_payload: dict[str, Any],
        plan_entries: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        desired = self._desired_instance_sync(plan_payload, plan_entries)
        raw_diners = plan_payload.get("diners")
        default_servings = int(raw_diners) if isinstance(raw_diners, int) and raw_diners > 0 else 2

        for entry in plan_entries:
            if not isinstance(entry, dict):
                continue

            entry_id = entry.get("entry_id")
            if not isinstance(entry_id, int):
                continue

            mode = str(entry.get("mode") or "planned")
            if mode not in {"leftover", "takeout", "empty"}:
                continue

            primary_recipe = entry.get("recipe")
            has_primary_recipe = isinstance(primary_recipe, dict) and isinstance(primary_recipe.get("id"), int)
            if has_primary_recipe:
                continue

            raw_servings = entry.get("servings")
            servings = int(raw_servings) if isinstance(raw_servings, int) and raw_servings > 0 else default_servings
            entry_date = entry.get("date")
            entry_date_text = str(entry_date) if isinstance(entry_date, str) else ""
            instance_key = self._instance_key_for_mode(entry_id=entry_id, mode=mode)
            desired[instance_key] = {
                "instance_key": instance_key,
                "entry_id": entry_id,
                "recipe_id": None,
                "role": "primary",
                "slot_index": None,
                "purpose": mode,
                "date": entry_date_text,
                "servings": servings,
                "entry_ids": set(),
                "meal_plan_row_id": None,
            }

        return desired

    def _normalize_instance_row(self, *, instance_key: str, row: dict[str, Any]) -> dict[str, Any] | None:
        recipe_id = row.get("recipe_id")
        if recipe_id is not None and (not isinstance(recipe_id, int) or recipe_id < 1):
            return None

        servings = row.get("servings")
        if not isinstance(servings, int) or servings < 1:
            return None

        raw_entry_ids = row.get("entry_ids")
        entry_ids: set[int] = set()
        if isinstance(raw_entry_ids, list):
            for raw_id in raw_entry_ids:
                if isinstance(raw_id, int) and raw_id > 0:
                    entry_ids.add(raw_id)
        elif isinstance(raw_entry_ids, set):
            for raw_id in raw_entry_ids:
                if isinstance(raw_id, int) and raw_id > 0:
                    entry_ids.add(raw_id)

        meal_plan_row_id = row.get("meal_plan_row_id")
        if not isinstance(meal_plan_row_id, int) or meal_plan_row_id < 1:
            meal_plan_row_id = None

        entry_id = row.get("entry_id")
        if not isinstance(entry_id, int):
            entry_id = 0

        role = row.get("role")
        if role not in {"primary", "extra"}:
            role = "primary"

        slot_index = row.get("slot_index")
        if not isinstance(slot_index, int):
            slot_index = None

        purpose = row.get("purpose")
        if purpose is not None:
            purpose = str(purpose)

        date_value = row.get("date")
        if not isinstance(date_value, str):
            date_value = ""

        return {
            "instance_key": instance_key,
            "entry_id": entry_id,
            "recipe_id": recipe_id,
            "role": role,
            "slot_index": slot_index,
            "purpose": purpose,
            "date": date_value,
            "servings": servings,
            "entry_ids": entry_ids,
            "meal_plan_row_id": meal_plan_row_id,
        }

    def _is_not_found_error(self, exc: TandoorError) -> bool:
        return "returned 404" in str(exc)

    async def _default_meal_type_payload(self) -> dict[str, Any]:
        meal_types = await self._client.list_meal_types(limit=50)
        rows = self._extract_results(meal_types)
        if len(rows) == 0:
            raise TandoorError("No meal types are configured in Tandoor.")

        preferred: dict[str, Any] | None = None
        for row in rows:
            name = row.get("name")
            if isinstance(name, str) and ("aftensmad" in name.lower() or "dinner" in name.lower()):
                preferred = row
                break
        if preferred is None:
            preferred = rows[0]

        meal_type_id = preferred.get("id")
        meal_type_name = preferred.get("name")
        if not isinstance(meal_type_id, int) or not isinstance(meal_type_name, str):
            raise TandoorError("Meal type payload from Tandoor is invalid.")

        payload: dict[str, Any] = {
            "id": meal_type_id,
            "name": meal_type_name,
            "order": int(preferred.get("order") or 0),
        }
        meal_type_time = preferred.get("time")
        if isinstance(meal_type_time, str):
            payload["time"] = meal_type_time
        meal_type_color = preferred.get("color")
        if isinstance(meal_type_color, str):
            payload["color"] = meal_type_color
        return payload

    async def _list_remote_meal_plan_ids(self) -> set[int]:
        payload = await self._client.list_meal_plans(limit=500)
        rows = self._extract_results(payload)
        ids: set[int] = set()
        for row in rows:
            row_id = row.get("id")
            if isinstance(row_id, int) and row_id > 0:
                ids.add(row_id)
        return ids

    async def _delete_meal_plan_row_if_present(self, row_id: int | None) -> None:
        if not isinstance(row_id, int) or row_id < 1:
            return
        try:
            await self._client.delete_meal_plan(row_id)
        except TandoorError as exc:
            if self._is_not_found_error(exc):
                return
            raise

    async def _create_meal_plan_row_for_instance(self, instance: dict[str, Any]) -> int:
        recipe_id = instance.get("recipe_id")
        servings = instance.get("servings")
        from_date = instance.get("date")
        if not isinstance(servings, int) or not isinstance(from_date, str):
            raise TandoorError("Cannot create meal-plan row: instance is missing required fields.")

        meal_type_payload = await self._default_meal_type_payload()
        iso_date = f"{from_date}T18:00:00Z"

        mode_label = None
        purpose = instance.get("purpose")
        if isinstance(purpose, str):
            if purpose == "leftover":
                mode_label = "Leftovers"
            elif purpose == "takeout":
                mode_label = "Takeout"
            elif purpose == "empty":
                mode_label = "Eating Out"

        if isinstance(recipe_id, int):
            title = f"WFD {from_date} Recipe {recipe_id}"
        elif isinstance(mode_label, str):
            title = f"WFD {from_date} {mode_label}"
        else:
            title = f"WFD {from_date}"

        payload = {
            "title": title,
            "servings": servings,
            "from_date": iso_date,
            "to_date": iso_date,
            "meal_type": meal_type_payload,
            "addshopping": False,
            "note": f"wfd-instance:{instance.get('instance_key')}",
        }
        if isinstance(recipe_id, int):
            payload["recipe"] = recipe_id
        result = await self._client.create_meal_plan(payload)
        row_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(row_id, int) or row_id < 1:
            raise TandoorError("Tandoor meal-plan create did not return an id.")
        return row_id

    def _serialize_instance_sync(self, instance_sync: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        serialized: dict[str, dict[str, Any]] = {}
        for instance_key, row in instance_sync.items():
            raw_entry_ids = row.get("entry_ids")
            entry_ids: list[int] = []
            if isinstance(raw_entry_ids, set):
                entry_ids = sorted(int(v) for v in raw_entry_ids if isinstance(v, int) and v > 0)
            elif isinstance(raw_entry_ids, list):
                entry_ids = sorted(int(v) for v in raw_entry_ids if isinstance(v, int) and v > 0)

            serialized[instance_key] = {
                "instance_key": str(row.get("instance_key") or instance_key),
                "entry_id": int(row.get("entry_id") or 0),
                "recipe_id": int(row.get("recipe_id")) if isinstance(row.get("recipe_id"), int) else None,
                "role": str(row.get("role") or "primary"),
                "slot_index": row.get("slot_index") if isinstance(row.get("slot_index"), int) else None,
                "purpose": str(row.get("purpose")) if row.get("purpose") is not None else None,
                "date": str(row.get("date") or ""),
                "servings": int(row.get("servings")),
                "entry_ids": entry_ids,
                "meal_plan_row_id": row.get("meal_plan_row_id")
                if isinstance(row.get("meal_plan_row_id"), int) and int(row.get("meal_plan_row_id")) > 0
                else None,
            }
        return serialized

    async def _sync_tandoor_meal_plan_rows(
        self,
        *,
        plan_id: int,
        plan_payload: dict[str, Any],
        ensure_tandoor_writes_enabled,
        operation_name: str,
    ) -> None:
        ensure_tandoor_writes_enabled(operation_name)

        entries = plan_payload.get("entries")
        if not isinstance(entries, list):
            entries = []

        desired_sync = self._desired_meal_plan_row_sync(plan_payload, entries)

        previous_sync: dict[str, dict[str, Any]] = {}
        raw_previous_sync = self._state.get_meal_plan_instance_sync(plan_id)
        for key, value in raw_previous_sync.items():
            if not isinstance(value, dict):
                continue
            normalized = self._normalize_instance_row(instance_key=str(key), row=value)
            if isinstance(normalized, dict):
                previous_sync[str(key)] = normalized

        retained_removed_sync: dict[str, dict[str, Any]] = {}
        for instance_key in sorted(previous_sync.keys()):
            if instance_key in desired_sync:
                continue
            previous_row = previous_sync[instance_key]
            await self._delete_meal_plan_row_if_present(previous_row.get("meal_plan_row_id"))
            retained_row = dict(previous_row)
            retained_row["meal_plan_row_id"] = None
            retained_removed_sync[instance_key] = retained_row

        remote_ids = await self._list_remote_meal_plan_ids()
        next_sync: dict[str, dict[str, Any]] = dict(retained_removed_sync)

        for instance_key in sorted(desired_sync.keys()):
            desired_row = dict(desired_sync[instance_key])
            previous_row = previous_sync.get(instance_key)

            if isinstance(previous_row, dict):
                previous_ids = previous_row.get("entry_ids")
                if isinstance(previous_ids, set):
                    desired_row["entry_ids"] = set(previous_ids)

                unchanged = (
                    previous_row.get("recipe_id") == desired_row.get("recipe_id")
                    and int(previous_row.get("servings")) == int(desired_row.get("servings"))
                    and str(previous_row.get("date") or "") == str(desired_row.get("date") or "")
                )
                previous_row_id = previous_row.get("meal_plan_row_id")
                if unchanged and isinstance(previous_row_id, int) and previous_row_id in remote_ids:
                    desired_row["meal_plan_row_id"] = previous_row_id
                    next_sync[instance_key] = desired_row
                    continue

                await self._delete_meal_plan_row_if_present(previous_row_id)

            created_row_id = await self._create_meal_plan_row_for_instance(desired_row)
            desired_row["meal_plan_row_id"] = created_row_id
            remote_ids.add(created_row_id)
            next_sync[instance_key] = desired_row

        serializable_sync = self._serialize_instance_sync(next_sync)
        self._state.set_meal_plan_instance_sync(plan_id, serializable_sync)

    async def _delete_all_tandoor_meal_plan_rows(
        self,
        *,
        plan_id: int,
        ensure_tandoor_writes_enabled,
        operation_name: str,
    ) -> None:
        ensure_tandoor_writes_enabled(operation_name)
        previous_sync = self._state.get_meal_plan_instance_sync(plan_id)
        for _, value in previous_sync.items():
            if not isinstance(value, dict):
                continue
            row_id = value.get("meal_plan_row_id")
            await self._delete_meal_plan_row_if_present(row_id)

    async def generate_plan(
        self,
        *,
        start_day: date,
        length_days: int,
        diners: int,
        constraints: dict[str, list[int | str]],
        keyword_ids: list[int],
        no_repeat_days: int,
        ensure_tandoor_writes_enabled=None,
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
                    "extra_recipes": [],
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
        if ensure_tandoor_writes_enabled is not None:
            try:
                await self._sync_tandoor_meal_plan_rows(
                    plan_id=int(stored["plan_id"]),
                    plan_payload=stored,
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_generate",
                )
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        self._state.append_sync_event("meal_plan_generated", stored)
        return {"source": "tandoor+local-state", "data": self._enrich_plan_recipe_urls(stored)}

    async def patch_plan(self, plan_id: int, payload: dict[str, Any], ensure_tandoor_writes_enabled=None) -> dict:
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

        if ensure_tandoor_writes_enabled is not None:
            try:
                await self._sync_tandoor_meal_plan_rows(
                    plan_id=plan_id,
                    plan_payload=updated,
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_patch",
                )
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        self._state.append_sync_event("meal_plan_updated", {"plan_id": plan_id, "payload": payload})
        return {"source": "local-state", "data": self._enrich_plan_recipe_urls(updated)}

    async def add_entry(self, plan_id: int, payload: dict[str, Any], ensure_tandoor_writes_enabled=None) -> dict:
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
            "extra_recipes": payload.get("extra_recipes") if isinstance(payload.get("extra_recipes"), list) else [],
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

        if ensure_tandoor_writes_enabled is not None and isinstance(updated, dict):
            try:
                await self._sync_tandoor_meal_plan_rows(
                    plan_id=plan_id,
                    plan_payload=updated,
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_add_entry",
                )
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        self._state.append_sync_event("meal_plan_entry_added", {"plan_id": plan_id, "entry": entry})

        return {"source": "local-state", "data": self._enrich_plan_recipe_urls(updated)}

    async def patch_entry(
        self,
        plan_id: int,
        entry_id: int,
        payload: dict[str, Any],
        ensure_tandoor_writes_enabled=None,
    ) -> dict:
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
            "extra_recipes",
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

        if ensure_tandoor_writes_enabled is not None and isinstance(updated, dict):
            try:
                await self._sync_tandoor_meal_plan_rows(
                    plan_id=plan_id,
                    plan_payload=updated,
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_patch_entry",
                )
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        self._state.append_sync_event(
            "meal_plan_entry_updated",
            {"plan_id": plan_id, "entry_id": entry_id, "payload": payload},
        )

        return {"source": "local-state", "data": self._enrich_plan_recipe_urls(updated)}

    async def delete_entry(self, plan_id: int, entry_id: int, ensure_tandoor_writes_enabled=None) -> dict:
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

        if ensure_tandoor_writes_enabled is not None and isinstance(updated, dict):
            try:
                await self._sync_tandoor_meal_plan_rows(
                    plan_id=plan_id,
                    plan_payload=updated,
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_delete_entry",
                )
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        self._state.append_sync_event("meal_plan_entry_deleted", {"plan_id": plan_id, "entry_id": entry_id})

        return {"source": "local-state", "data": updated}

    async def delete_plan(self, plan_id: int, ensure_tandoor_writes_enabled=None) -> dict:
        plan = self._state.get_meal_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        if ensure_tandoor_writes_enabled is not None:
            try:
                await self._delete_all_tandoor_meal_plan_rows(
                    plan_id=plan_id,
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_delete",
                )
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        deleted = self._state.delete_meal_plan(plan_id)
        if deleted is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        self._state.append_sync_event("meal_plan_deleted", {"plan_id": plan_id})
        return {
            "source": "local-state",
            "data": {
                "deleted": True,
                "plan_id": plan_id,
            },
        }

    async def generate_shopping_from_plan(
        self,
        *,
        plan_id: int,
        mode: str = "sync",
        ensure_tandoor_writes_enabled,
        build_shopping_view,
    ) -> dict:
        def shopping_entry_recipe_id(shopping_entry: dict[str, Any]) -> int | None:
            list_recipe_data = shopping_entry.get("list_recipe_data")
            if not isinstance(list_recipe_data, dict):
                return None
            recipe_data = list_recipe_data.get("recipe_data")
            if not isinstance(recipe_data, dict):
                return None
            recipe_id = recipe_data.get("id")
            return recipe_id if isinstance(recipe_id, int) else None

        def recipe_entry_ids_by_recipe(shopping_entries: list[dict[str, Any]]) -> dict[int, set[int]]:
            mapped: dict[int, set[int]] = {}
            for shopping_entry in shopping_entries:
                if not isinstance(shopping_entry, dict):
                    continue
                entry_id = shopping_entry.get("id")
                if not isinstance(entry_id, int):
                    continue
                recipe_id = shopping_entry_recipe_id(shopping_entry)
                if not isinstance(recipe_id, int):
                    continue
                mapped.setdefault(recipe_id, set()).add(entry_id)
            return mapped

        def normalize_previous_instance_sync() -> dict[str, dict[str, Any]]:
            normalized: dict[str, dict[str, Any]] = {}
            raw_instance_sync = self._state.get_meal_plan_instance_sync(plan_id)
            for key, value in raw_instance_sync.items():
                if not isinstance(value, dict):
                    continue
                instance = self._normalize_instance_row(instance_key=str(key), row=value)
                if isinstance(instance, dict):
                    normalized[str(key)] = instance
            return normalized

        async def list_shopping_entries() -> list[dict[str, Any]]:
            payload = await self._client.list_shopping_entries(limit=500)
            return self._extract_results(payload)

        async def create_meal_plan_row(
            *,
            instance: dict[str, Any],
            recipe_source: str,
            created: list[dict[str, Any]],
            failed: list[dict[str, Any]],
        ) -> int | None:
            try:
                row_id = await self._create_meal_plan_row_for_instance(instance)
            except TandoorError as exc:
                failed.append(
                    {
                        "operation": "meal_plan_upsert",
                        "recipe_source": recipe_source,
                        "instance_key": instance.get("instance_key"),
                        "recipe_id": instance.get("recipe_id"),
                        "errors": [str(exc)],
                    }
                )
                return None

            created.append(
                {
                    "operation": "meal_plan_upsert",
                    "recipe_source": recipe_source,
                    "instance_key": instance.get("instance_key"),
                    "recipe_id": instance.get("recipe_id"),
                    "result": {"id": row_id},
                }
            )
            return row_id

        async def delete_meal_plan_row(
            *,
            instance: dict[str, Any],
            recipe_source: str,
            created: list[dict[str, Any]],
            failed: list[dict[str, Any]],
        ) -> bool:
            row_id = instance.get("meal_plan_row_id")
            if not isinstance(row_id, int) or row_id < 1:
                return True

            try:
                result = await self._client.delete_meal_plan(row_id)
            except TandoorError as exc:
                if self._is_not_found_error(exc):
                    created.append(
                        {
                            "operation": "meal_plan_delete",
                            "recipe_source": recipe_source,
                            "instance_key": instance.get("instance_key"),
                            "meal_plan_row_id": row_id,
                            "result": {"deleted": row_id, "note": "already_missing"},
                        }
                    )
                    return True
                failed.append(
                    {
                        "operation": "meal_plan_delete",
                        "recipe_source": recipe_source,
                        "instance_key": instance.get("instance_key"),
                        "meal_plan_row_id": row_id,
                        "errors": [str(exc)],
                    }
                )
                return False

            created.append(
                {
                    "operation": "meal_plan_delete",
                    "recipe_source": recipe_source,
                    "instance_key": instance.get("instance_key"),
                    "meal_plan_row_id": row_id,
                    "result": result,
                }
            )
            return True

        async def delete_tracked_entries(
            *,
            recipe_id: int,
            tracked_ids: set[int],
            instance_key: str,
            recipe_source: str,
            created: list[dict[str, Any]],
            failed: list[dict[str, Any]],
        ) -> set[int]:
            remaining: set[int] = set()
            for entry_id in sorted(tracked_ids):
                try:
                    result = await self._client.delete_shopping_entry(entry_id)
                    created.append(
                        {
                            "operation": "shopping_entry_delete",
                            "recipe_source": recipe_source,
                            "instance_key": instance_key,
                            "recipe_id": recipe_id,
                            "entry_id": entry_id,
                            "result": result,
                        }
                    )
                except TandoorError as exc:
                    if self._is_not_found_error(exc):
                        created.append(
                            {
                                "operation": "shopping_entry_delete",
                                "recipe_source": recipe_source,
                                "instance_key": instance_key,
                                "recipe_id": recipe_id,
                                "entry_id": entry_id,
                                "result": {"deleted": entry_id, "note": "already_missing"},
                            }
                        )
                        continue
                    remaining.add(entry_id)
                    failed.append(
                        {
                            "operation": "shopping_entry_delete",
                            "recipe_source": recipe_source,
                            "instance_key": instance_key,
                            "recipe_id": recipe_id,
                            "entry_id": entry_id,
                            "errors": [str(exc)],
                        }
                    )
            return remaining

        async def run_recipe_update(
            *,
            instance_key: str,
            recipe_id: int,
            servings: int,
            ingredient_ids: list[int],
            recipe_source: str,
            created: list[dict[str, Any]],
            failed: list[dict[str, Any]],
        ) -> tuple[set[int], set[int]] | None:
            request_payload = {"ingredients": ingredient_ids, "servings": servings}

            try:
                before_entries = await list_shopping_entries()
            except TandoorError as exc:
                failed.append(
                    {
                        "operation": "recipe_shopping_update",
                        "recipe_source": recipe_source,
                        "instance_key": instance_key,
                        "recipe_id": recipe_id,
                        "payload": request_payload,
                        "errors": [str(exc)],
                    }
                )
                return None

            before_ids = recipe_entry_ids_by_recipe(before_entries).get(recipe_id, set())

            try:
                result = await self._client.update_recipe_shopping(recipe_id, request_payload)
            except TandoorError as exc:
                failed.append(
                    {
                        "operation": "recipe_shopping_update",
                        "recipe_source": recipe_source,
                        "instance_key": instance_key,
                        "recipe_id": recipe_id,
                        "payload": request_payload,
                        "errors": [str(exc)],
                    }
                )
                return None

            try:
                after_entries = await list_shopping_entries()
            except TandoorError as exc:
                failed.append(
                    {
                        "operation": "recipe_shopping_update",
                        "recipe_source": recipe_source,
                        "instance_key": instance_key,
                        "recipe_id": recipe_id,
                        "payload": request_payload,
                        "errors": [str(exc)],
                    }
                )
                return None

            after_ids = recipe_entry_ids_by_recipe(after_entries).get(recipe_id, set())
            added_ids = {entry_id for entry_id in after_ids if entry_id not in before_ids}

            created.append(
                {
                    "operation": "recipe_shopping_update",
                    "recipe_source": recipe_source,
                    "instance_key": instance_key,
                    "recipe_id": recipe_id,
                    "payload": request_payload,
                    "result": result,
                    "added_entry_ids": sorted(added_ids),
                }
            )
            return after_ids, added_ids

        async def finalize_generation(
            *,
            plan_id: int,
            mode: str,
            next_sync: dict[str, dict[str, Any]],
            created: list[dict[str, Any]],
            failed: list[dict[str, Any]],
        ) -> dict:
            serializable_sync = self._serialize_instance_sync(next_sync)

            self._state.set_meal_plan_instance_sync(plan_id, serializable_sync)

            self._state.append_sync_event(
                "meal_plan_shopping_generated",
                {
                    "plan_id": plan_id,
                    "mode": mode,
                    "created_count": len(created),
                    "failed_count": len(failed),
                },
            )

            shopping_view: dict[str, Any] | None = None
            shopping_view_error: str | None = None
            try:
                refreshed_entries = await list_shopping_entries()
                shopping_view = build_shopping_view(refreshed_entries)
            except TandoorError as exc:
                shopping_view_error = str(exc)

            return {
                "source": "tandoor+local-state",
                "data": {
                    "plan_id": plan_id,
                    "mode": mode,
                    "created": created,
                    "failed": failed,
                    "created_count": len(created),
                    "failed_count": len(failed),
                    "shopping_view": shopping_view,
                    "shopping_view_error": shopping_view_error,
                },
            }

        lock = self._shopping_generation_locks.get(plan_id)
        if lock is None:
            lock = asyncio.Lock()
            self._shopping_generation_locks[plan_id] = lock

        async with lock:
            ensure_tandoor_writes_enabled("meal_plan_to_shopping_list")
            plan = self._state.get_meal_plan(plan_id)
            if plan is None:
                raise HTTPException(status_code=404, detail="Meal plan not found.")

            entries = plan.get("entries")
            if not isinstance(entries, list):
                entries = []

            created: list[dict[str, Any]] = []
            failed: list[dict[str, Any]] = []

            try:
                shopping_entries = await list_shopping_entries()
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            current_recipe_entries = recipe_entry_ids_by_recipe(shopping_entries)
            previous_sync = normalize_previous_instance_sync()
            desired_sync = self._desired_instance_sync(plan, entries)
            next_sync: dict[str, dict[str, Any]] = {}

            if mode == "regenerate_missing":
                for previous_key, previous_row in previous_sync.items():
                    if previous_key not in desired_sync:
                        next_sync[previous_key] = dict(previous_row)

                for instance_key in sorted(desired_sync.keys()):
                    desired_row = dict(desired_sync[instance_key])
                    recipe_id = desired_row["recipe_id"]
                    desired_servings = desired_row["servings"]
                    previous_row = previous_sync.get(instance_key)

                    tracked_ids: set[int] = set()
                    meal_plan_row_id: int | None = None
                    if isinstance(previous_row, dict):
                        prev_ids = previous_row.get("entry_ids")
                        if isinstance(prev_ids, set):
                            tracked_ids = set(prev_ids)
                        meal_plan_row_id = (
                            previous_row.get("meal_plan_row_id")
                            if isinstance(previous_row.get("meal_plan_row_id"), int)
                            else None
                        )

                    current_ids = current_recipe_entries.get(recipe_id, set())
                    if len(tracked_ids) > 0 and tracked_ids.issubset(current_ids):
                        desired_row["entry_ids"] = tracked_ids
                        desired_row["meal_plan_row_id"] = meal_plan_row_id
                        next_sync[instance_key] = desired_row
                        continue

                    try:
                        recipe_payload = await self._client.get_recipe(recipe_id)
                        ingredient_ids = self._extract_recipe_ingredient_ids(recipe_payload)
                    except TandoorError as exc:
                        failed.append(
                            {
                                "operation": "recipe_shopping_update",
                                "recipe_source": "regenerate_missing",
                                "instance_key": instance_key,
                                "recipe_id": recipe_id,
                                "payload": {"ingredients": [], "servings": desired_servings},
                                "errors": [str(exc)],
                            }
                        )
                        if isinstance(previous_row, dict):
                            next_sync[instance_key] = dict(previous_row)
                        continue

                    update_result = await run_recipe_update(
                        instance_key=instance_key,
                        recipe_id=recipe_id,
                        servings=desired_servings,
                        ingredient_ids=ingredient_ids,
                        recipe_source="regenerate_missing",
                        created=created,
                        failed=failed,
                    )
                    if update_result is None:
                        if isinstance(previous_row, dict):
                            next_sync[instance_key] = dict(previous_row)
                        continue

                    _, added_ids = update_result
                    tracked_ids.update(added_ids)
                    desired_row["entry_ids"] = tracked_ids
                    desired_row["meal_plan_row_id"] = meal_plan_row_id
                    next_sync[instance_key] = desired_row

                try:
                    remote_meal_plan_ids = await self._list_remote_meal_plan_ids()
                except TandoorError:
                    failed.append(
                        {
                            "operation": "meal_plan_list",
                            "recipe_source": "regenerate_missing",
                            "errors": ["Unable to list remote meal-plan rows."],
                        }
                    )
                else:
                    for instance_key in sorted(desired_sync.keys()):
                        row = next_sync.get(instance_key)
                        if not isinstance(row, dict):
                            continue
                        row_id = row.get("meal_plan_row_id")
                        if isinstance(row_id, int) and row_id in remote_meal_plan_ids:
                            continue
                        created_row_id = await create_meal_plan_row(
                            instance=row,
                            recipe_source="regenerate_missing",
                            created=created,
                            failed=failed,
                        )
                        if isinstance(created_row_id, int):
                            row["meal_plan_row_id"] = created_row_id
                            remote_meal_plan_ids.add(created_row_id)

                return await finalize_generation(
                    plan_id=plan_id,
                    mode="regenerate_missing",
                    next_sync=next_sync,
                    created=created,
                    failed=failed,
                )

            removed_instance_keys = sorted(
                instance_key for instance_key in previous_sync.keys() if instance_key not in desired_sync
            )
            for instance_key in removed_instance_keys:
                previous_row = previous_sync[instance_key]
                recipe_id = previous_row.get("recipe_id")
                previous_ids = set(previous_row.get("entry_ids") if isinstance(previous_row.get("entry_ids"), set) else set())
                remaining_ids: set[int] = set(previous_ids)
                if isinstance(recipe_id, int):
                    remaining_ids = await delete_tracked_entries(
                        recipe_id=recipe_id,
                        tracked_ids=previous_ids,
                        instance_key=instance_key,
                        recipe_source="sync_remove",
                        created=created,
                        failed=failed,
                    )
                meal_plan_deleted = await delete_meal_plan_row(
                    instance=previous_row,
                    recipe_source="sync_remove",
                    created=created,
                    failed=failed,
                )

                if len(remaining_ids) > 0 or not meal_plan_deleted:
                    retained = dict(previous_row)
                    retained["entry_ids"] = remaining_ids
                    next_sync[instance_key] = retained

            for instance_key in sorted(desired_sync.keys()):
                desired_row = dict(desired_sync[instance_key])
                recipe_id = int(desired_row["recipe_id"])
                desired_servings = int(desired_row["servings"])
                previous_row = previous_sync.get(instance_key)

                previous_ids: set[int] = set()
                previous_meal_plan_row_id: int | None = None
                previous_servings: int | None = None
                previous_date: str | None = None
                if isinstance(previous_row, dict):
                    previous_servings = int(previous_row["servings"])
                    previous_date = str(previous_row.get("date") or "")
                    raw_previous_ids = previous_row.get("entry_ids")
                    if isinstance(raw_previous_ids, set):
                        previous_ids = set(raw_previous_ids)
                    previous_meal_plan_row_id = (
                        previous_row.get("meal_plan_row_id")
                        if isinstance(previous_row.get("meal_plan_row_id"), int)
                        else None
                    )

                current_ids = set(current_recipe_entries.get(recipe_id, set()))
                is_stale = len(previous_ids) > 0 and not previous_ids.issubset(current_ids)
                is_changed = previous_servings != desired_servings or previous_date != str(desired_row.get("date") or "")

                if isinstance(previous_row, dict) and not is_stale and not is_changed and len(previous_ids) > 0:
                    desired_row["entry_ids"] = previous_ids
                    desired_row["meal_plan_row_id"] = previous_meal_plan_row_id
                    next_sync[instance_key] = desired_row
                    continue

                if isinstance(previous_row, dict):
                    remaining_ids = await delete_tracked_entries(
                        recipe_id=recipe_id,
                        tracked_ids=previous_ids,
                        instance_key=instance_key,
                        recipe_source="sync_refresh",
                        created=created,
                        failed=failed,
                    )
                    if len(remaining_ids) > 0:
                        retained = dict(previous_row)
                        retained["entry_ids"] = remaining_ids
                        next_sync[instance_key] = retained
                        failed.append(
                            {
                                "operation": "recipe_shopping_update",
                                "recipe_source": "sync_upsert",
                                "instance_key": instance_key,
                                "recipe_id": recipe_id,
                                "payload": {"servings": desired_servings},
                                "errors": ["Instance sync skipped because tracked entries could not be removed."],
                            }
                        )
                        continue

                    meal_plan_deleted = await delete_meal_plan_row(
                        instance=previous_row,
                        recipe_source="sync_refresh",
                        created=created,
                        failed=failed,
                    )
                    if not meal_plan_deleted:
                        next_sync[instance_key] = dict(previous_row)
                        continue

                try:
                    recipe_payload = await self._client.get_recipe(recipe_id)
                    ingredient_ids = self._extract_recipe_ingredient_ids(recipe_payload)
                except TandoorError as exc:
                    failed.append(
                        {
                            "operation": "recipe_shopping_update",
                            "recipe_source": "sync_upsert",
                            "instance_key": instance_key,
                            "recipe_id": recipe_id,
                            "payload": {"ingredients": [], "servings": desired_servings},
                            "errors": [str(exc)],
                        }
                    )
                    continue

                update_result = await run_recipe_update(
                    instance_key=instance_key,
                    recipe_id=recipe_id,
                    servings=desired_servings,
                    ingredient_ids=ingredient_ids,
                    recipe_source="sync_upsert",
                    created=created,
                    failed=failed,
                )
                if update_result is None:
                    continue

                _, added_ids = update_result
                desired_row["entry_ids"] = set(added_ids)
                desired_row["meal_plan_row_id"] = None
                next_sync[instance_key] = desired_row

            try:
                remote_meal_plan_ids = await self._list_remote_meal_plan_ids()
            except TandoorError:
                failed.append(
                    {
                        "operation": "meal_plan_list",
                        "recipe_source": "sync",
                        "errors": ["Unable to list remote meal-plan rows."],
                    }
                )
            else:
                for instance_key in sorted(desired_sync.keys()):
                    row = next_sync.get(instance_key)
                    if not isinstance(row, dict):
                        continue
                    row_id = row.get("meal_plan_row_id")
                    if isinstance(row_id, int) and row_id in remote_meal_plan_ids:
                        continue
                    created_row_id = await create_meal_plan_row(
                        instance=row,
                        recipe_source="sync_upsert",
                        created=created,
                        failed=failed,
                    )
                    if isinstance(created_row_id, int):
                        row["meal_plan_row_id"] = created_row_id
                        remote_meal_plan_ids.add(created_row_id)

            return await finalize_generation(
                plan_id=plan_id,
                mode="sync",
                next_sync=next_sync,
                created=created,
                failed=failed,
            )
