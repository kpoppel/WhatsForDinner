"""Meal-plan generation and Tandoor projection orchestration.

Local derived plans are accepted before their Tandoor projection. Failed
projections become durable, explicitly retried operations; instance notes make
ambiguous upstream creates reconcilable without duplicating meal-plan rows.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import random
import re
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException

from app.config import settings
from app.services.stage2_state import Stage2State
from app.services.tandoor_client import TandoorClient, TandoorError


class MealPlanService:
    """Apply meal-plan rules and reconcile local plans with Tandoor rows."""

    def __init__(self, state: Stage2State, tandoor_client: TandoorClient) -> None:
        self._state = state
        self._client = tandoor_client
        self._shopping_generation_locks: dict[int, asyncio.Lock] = {}
        self._meal_plan_mutation_locks: dict[int, asyncio.Lock] = {}

    def _get_plan_mutation_lock(self, plan_id: int) -> asyncio.Lock:
        """Get or create an asyncio.Lock for mutations on a specific meal plan."""
        if plan_id not in self._meal_plan_mutation_locks:
            self._meal_plan_mutation_locks[plan_id] = asyncio.Lock()
        return self._meal_plan_mutation_locks[plan_id]

    def _ensure_plan_token(self, plan_id: int, plan_payload: dict[str, Any]) -> str:
        """Persist the immutable marker used to associate Tandoor rows with one plan."""
        plan_token = plan_payload.get("plan_token")
        if isinstance(plan_token, str) and plan_token:
            return plan_token

        plan_token = uuid.uuid4().hex
        updated = self._state.update_meal_plan(plan_id, {"plan_token": plan_token})
        if updated is None:
            raise TandoorError("Meal plan no longer exists while assigning its ownership token.")
        plan_payload["plan_token"] = plan_token
        return plan_token

    def _response(
        self,
        source: str,
        data: Any,
        projection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "source": source,
            "revision": self._state.current_revision(),
            "projection": projection or {"status": "synchronized"},
            "pending_projections": self._state.pending_projections(),
            "data": data,
        }

    def _pending_projection_response(
        self,
        data: Any,
        operation: str,
        payload: dict[str, Any],
        error: str,
    ) -> dict[str, Any]:
        pending = self._state.create_pending_projection("meal_plan", operation, payload, error)
        return self._response("local-state", data, pending)

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
        for use in self._state.recipe_use_history():
            recipe_id = use.get("recipe_id")
            date_value = use.get("used_date")
            if not isinstance(recipe_id, int) or not isinstance(date_value, str):
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
            if seen_date > candidate_date:
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
        normalized, _ = self._merge_duplicate_date_entries(entries)
        start_day: date | None
        try:
            start_day = date.fromisoformat(str(plan_start_date))
        except ValueError:
            start_day = None

        normalized.sort(key=lambda row: int(row.get("day_index", 0)))
        for idx, row in enumerate(normalized):
            row["day_index"] = idx
            if start_day is not None:
                row["date"] = (start_day + timedelta(days=idx)).isoformat()
        return normalized

    def _merge_duplicate_date_entries(
        self,
        entries: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[int, int]]:
        """Keep one card per date while preserving recipes from merged cards."""
        merged: list[dict[str, Any]] = []
        by_date: dict[str, dict[str, Any]] = {}
        entry_id_remap: dict[int, int] = {}

        for raw_entry in entries:
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(raw_entry)
            entry_date = entry.get("date")
            if not isinstance(entry_date, str) or entry_date in by_date:
                canonical = by_date.get(entry_date) if isinstance(entry_date, str) else None
                if canonical is None:
                    merged.append(entry)
                    continue

                duplicate_id = entry.get("entry_id")
                canonical_id = canonical.get("entry_id")
                if isinstance(duplicate_id, int) and isinstance(canonical_id, int):
                    entry_id_remap[duplicate_id] = canonical_id

                canonical_recipe = canonical.get("recipe")
                duplicate_recipe = entry.get("recipe")
                if not isinstance(canonical_recipe, dict) and isinstance(duplicate_recipe, dict):
                    canonical["recipe"] = duplicate_recipe
                    canonical["mode"] = entry.get("mode", "planned")
                elif isinstance(duplicate_recipe, dict):
                    canonical_extras = canonical.get("extra_recipes")
                    if not isinstance(canonical_extras, list):
                        canonical_extras = []
                        canonical["extra_recipes"] = canonical_extras
                    canonical_extras.append(
                        {"recipe": duplicate_recipe, "purpose": "merged", "source": "local"}
                    )

                duplicate_extras = entry.get("extra_recipes")
                if isinstance(duplicate_extras, list):
                    canonical_extras = canonical.get("extra_recipes")
                    if not isinstance(canonical_extras, list):
                        canonical_extras = []
                        canonical["extra_recipes"] = canonical_extras
                    canonical_extras.extend(
                        extra for extra in duplicate_extras if isinstance(extra, dict)
                    )
                continue

            by_date[entry_date] = entry
            merged.append(entry)

        for entry in merged:
            extras = entry.get("extra_recipes")
            if not isinstance(extras, list):
                continue
            seen_row_ids: set[int] = set()
            deduplicated_extras: list[dict[str, Any]] = []
            for extra in extras:
                if not isinstance(extra, dict):
                    continue
                row_id = extra.get("tandoor_meal_plan_row_id")
                if isinstance(row_id, int):
                    if row_id in seen_row_ids:
                        continue
                    seen_row_ids.add(row_id)
                deduplicated_extras.append(extra)
            entry["extra_recipes"] = deduplicated_extras

        return merged, entry_id_remap

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
                        "recipe_title": self._recipe_title(primary_recipe),
                        "role": "primary",
                        "slot_index": None,
                        "purpose": "meal",
                        "date": entry_date_text,
                        "servings": servings,
                        "meal_plan_row_id": None,
                        "shopping_recipe_id": None,
                        "shopping_activated": False,
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
                    "recipe_title": self._recipe_title(recipe),
                    "role": "extra",
                    "slot_index": idx,
                    "purpose": str(purpose) if purpose is not None else "extra",
                    "date": entry_date_text,
                    "servings": servings,
                    "meal_plan_row_id": None,
                    "shopping_recipe_id": None,
                    "shopping_activated": False,
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

            primary_recipe = entry.get("recipe")
            has_primary_recipe = isinstance(primary_recipe, dict) and isinstance(primary_recipe.get("id"), int)
            if has_primary_recipe:
                continue

            mode = str(entry.get("mode") or "planned")
            if mode == "planned":
                mode = "empty"
            if mode not in {"leftover", "takeout", "empty"}:
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
                "recipe_title": None,
                "role": "primary",
                "slot_index": None,
                "purpose": mode,
                "date": entry_date_text,
                "servings": servings,
                "meal_plan_row_id": None,
                "shopping_recipe_id": None,
                "shopping_activated": False,
            }

        return desired

    def _normalize_instance_row(self, *, instance_key: str, row: dict[str, Any]) -> dict[str, Any] | None:
        recipe_id = row.get("recipe_id")
        if recipe_id is not None and (not isinstance(recipe_id, int) or recipe_id < 1):
            return None

        servings = row.get("servings")
        if not isinstance(servings, int) or servings < 1:
            return None

        meal_plan_row_id = row.get("meal_plan_row_id")
        if not isinstance(meal_plan_row_id, int) or meal_plan_row_id < 1:
            meal_plan_row_id = None

        shopping_recipe_id = row.get("shopping_recipe_id")
        if not isinstance(shopping_recipe_id, int) or shopping_recipe_id < 1:
            shopping_recipe_id = None

        shopping_activated = bool(row.get("shopping_activated", False))

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
            "recipe_title": str(row.get("recipe_title")) if isinstance(row.get("recipe_title"), str) else None,
            "role": role,
            "slot_index": slot_index,
            "purpose": purpose,
            "date": date_value,
            "servings": servings,
            "meal_plan_row_id": meal_plan_row_id,
            "shopping_recipe_id": shopping_recipe_id,
            "shopping_activated": shopping_activated,
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

    def _pending_operation_ids_for_plan(self, plan_id: int) -> set[str]:
        operation_ids: set[str] = set()
        for record in self._state.pending_projections():
            payload = record.get("payload")
            if (
                record.get("domain") == "meal_plan"
                and isinstance(payload, dict)
                and payload.get("plan_id") == plan_id
                and isinstance(record.get("operation_id"), str)
            ):
                operation_ids.add(record["operation_id"])
        return operation_ids

    async def _remote_meal_plan_rows_by_instance(self) -> dict[str, dict[str, Any]]:
        payload = await self._client.list_meal_plans(limit=500)
        rows = self._extract_results(payload)
        by_instance: dict[str, dict[str, Any]] = {}
        for row in rows:
            note = row.get("note")
            row_id = row.get("id")
            if not isinstance(note, str) or not note.startswith("wfd-plan:"):
                continue
            if not isinstance(row_id, int) or row_id < 1:
                continue
            _, separator, instance_key = note.partition(";wfd-instance:")
            if not separator or not instance_key:
                continue
            by_instance[note] = row
        return by_instance

    def _parse_tandoor_plan_marker(self, row: dict[str, Any]) -> tuple[str, str] | None:
        """Return immutable server ownership fields from a Tandoor row note."""
        note = row.get("note")
        if not isinstance(note, str):
            return None
        match = re.fullmatch(r"wfd-plan:([0-9a-f]{32});wfd-instance:(.+)", note)
        if match is None:
            return None
        return match.group(1), match.group(2)

    def _parse_legacy_tandoor_instance_marker(self, row: dict[str, Any]) -> str | None:
        """Return a legacy instance marker only while migrating existing server projections."""
        note = row.get("note")
        if not isinstance(note, str):
            return None
        match = re.fullmatch(r"wfd-instance:(entry:\d+:(?:primary:recipe:\d+|extra:\d+:recipe:\d+|mode:(?:leftover|takeout|empty)))", note)
        return match.group(1) if match is not None else None

    def _entry_id_from_instance_key(self, instance_key: str) -> int | None:
        """Extract the server entry identity from an immutable instance marker."""
        match = re.match(r"entry:(\d+):", instance_key)
        return int(match.group(1)) if match is not None else None

    def _entry_from_tandoor_row(
        self,
        *,
        row: dict[str, Any],
        instance_key: str,
        previous: dict[str, Any] | None,
        plan_start_date: str,
    ) -> dict[str, Any] | None:
        """Build one local presentation entry from one authoritative Tandoor row."""
        entry_id = self._entry_id_from_instance_key(instance_key)
        raw_date = str(row.get("from_date") or "").split("T", 1)[0]
        row_id = row.get("id")
        servings = row.get("servings")
        if entry_id is None or not isinstance(row_id, int) or not isinstance(servings, int):
            return None
        try:
            day_index = (date.fromisoformat(raw_date) - date.fromisoformat(plan_start_date)).days
        except ValueError:
            return None

        recipe_data = row.get("recipe")
        recipe_id = recipe_data.get("id") if isinstance(recipe_data, dict) else recipe_data
        recipe_title = (
            recipe_data.get("name") or recipe_data.get("title")
            if isinstance(recipe_data, dict)
            else row.get("title")
        )
        mode_match = re.fullmatch(r"entry:\d+:mode:(leftover|takeout|empty)", instance_key)
        mode = mode_match.group(1) if mode_match is not None else "planned"
        recipe = (
            {"id": recipe_id, "title": str(recipe_title or f"Recipe {recipe_id}"), "url": self._recipe_url(recipe_id)}
            if isinstance(recipe_id, int)
            else None
        )
        return {
            "entry_id": entry_id,
            "day_index": day_index,
            "date": raw_date,
            "mode": mode,
            "recipe": recipe,
            "extra_recipes": [],
            "servings": servings,
            "reminder_enabled": bool(previous.get("reminder_enabled", False)) if previous else False,
            "reminder_text": str(previous.get("reminder_text") or "") if previous else "",
            "notes": str(previous.get("notes") or "") if previous else "",
        }

    async def sync_from_tandoor(
        self,
        ensure_tandoor_writes_enabled=None,
        build_shopping_view=None,
    ) -> dict[str, Any]:
        """Rebuild local plan projections from the authoritative Tandoor snapshot."""
        try:
            payload = await self._client.list_meal_plans(limit=500)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        local_plans = self._state.list_meal_plans()
        entry_owner_plan_ids: dict[int, set[int]] = {}
        for plan in local_plans:
            plan_id = plan.get("plan_id")
            entries = plan.get("entries")
            if not isinstance(plan_id, int) or not isinstance(entries, list):
                continue
            for entry in entries:
                entry_id = entry.get("entry_id") if isinstance(entry, dict) else None
                if isinstance(entry_id, int):
                    entry_owner_plan_ids.setdefault(entry_id, set()).add(plan_id)

        plan_token_by_id: dict[int, str] = {}
        for plan in local_plans:
            plan_id = plan.get("plan_id")
            if isinstance(plan_id, int):
                plan_token_by_id[plan_id] = self._ensure_plan_token(plan_id, plan)

        rows_by_plan_token: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for row in self._extract_results(payload):
            marker = self._parse_tandoor_plan_marker(row)
            if marker is not None:
                plan_token, instance_key = marker
                rows_by_plan_token.setdefault(plan_token, []).append((instance_key, row))
                continue

            instance_key = self._parse_legacy_tandoor_instance_marker(row)
            entry_id = self._entry_id_from_instance_key(instance_key) if instance_key else None
            owner_ids = entry_owner_plan_ids.get(entry_id, set()) if isinstance(entry_id, int) else set()
            if len(owner_ids) != 1:
                continue
            plan_id = next(iter(owner_ids))
            plan_token = plan_token_by_id.get(plan_id)
            if isinstance(plan_token, str):
                rows_by_plan_token.setdefault(plan_token, []).append((instance_key, row))

        changed_plan_ids: list[int] = []
        for plan in local_plans:
            plan_id = plan.get("plan_id")
            if not isinstance(plan_id, int):
                continue
            plan_token = plan_token_by_id[plan_id]
            entries = plan.get("entries")
            if not isinstance(entries, list):
                entries = []
            previous_entries: dict[int, dict[str, Any]] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("entry_id")
                if isinstance(entry_id, int):
                    previous_entries[entry_id] = entry
            rebuilt_entries: dict[int, dict[str, Any]] = {}
            rebuilt_sync: dict[str, dict[str, Any]] = {}
            for instance_key, row in rows_by_plan_token.get(plan_token, []):
                entry = self._entry_from_tandoor_row(
                    row=row,
                    instance_key=instance_key,
                    previous=previous_entries.get(self._entry_id_from_instance_key(instance_key)),
                    plan_start_date=str(plan.get("start_date") or ""),
                )
                if entry is None:
                    continue
                entry_id = int(entry["entry_id"])
                if ":extra:" in instance_key:
                    primary = rebuilt_entries.setdefault(
                        entry_id,
                        {
                            **entry,
                            "recipe": None,
                            "mode": "planned",
                            "extra_recipes": [],
                        },
                    )
                    primary["extra_recipes"].append({"recipe": entry["recipe"], "purpose": "extra", "source": "tandoor", "tandoor_meal_plan_row_id": row["id"]})
                else:
                    existing = rebuilt_entries.get(entry_id)
                    if existing is not None:
                        entry["extra_recipes"] = existing["extra_recipes"]
                    rebuilt_entries[entry_id] = entry
                recipe_id = entry["recipe"].get("id") if isinstance(entry["recipe"], dict) else None
                rebuilt_sync[instance_key] = {
                    "instance_key": instance_key,
                    "entry_id": entry_id,
                    "recipe_id": recipe_id,
                    "recipe_title": entry["recipe"].get("title") if isinstance(entry["recipe"], dict) else None,
                    "role": "extra" if ":extra:" in instance_key else "primary",
                    "slot_index": None,
                    "purpose": entry["mode"],
                    "date": entry["date"],
                    "servings": entry["servings"],
                    "meal_plan_row_id": row["id"],
                    "shopping_recipe_id": None,
                    "shopping_activated": False,
                }
            next_entries = sorted(rebuilt_entries.values(), key=lambda entry: (entry["day_index"], entry["entry_id"]))
            if entries != next_entries:
                self._state.update_meal_plan(plan_id, {"entries": next_entries})
                changed_plan_ids.append(plan_id)
            self._state.set_meal_plan_instance_sync(plan_id, rebuilt_sync)
            self._state.record_meal_plan_recipe_uses(plan_id)

        return {
            "source": "tandoor-projection",
            "revision": self._state.current_revision(),
            "changed_plan_ids": sorted(changed_plan_ids),
            "changed_dates": [],
            "shopping_stale_plan_ids": [],
            "shopping_sync": [],
        }

        rows = self._extract_results(payload)
        rows_by_instance: dict[str, dict[str, Any]] = {}
        rows_by_id: dict[int, dict[str, Any]] = {}
        rows_by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            row_id = row.get("id")
            if not isinstance(row_id, int) or row_id < 1:
                continue
            rows_by_id[row_id] = row

            raw_date = row.get("from_date")
            row_date = str(raw_date or "").split("T", 1)[0]
            try:
                date.fromisoformat(row_date)
            except ValueError:
                continue

            note = row.get("note")
            if isinstance(note, str) and note.startswith("wfd-instance:"):
                rows_by_instance[note.removeprefix("wfd-instance:")] = row
            rows_by_date.setdefault(row_date, []).append(row)

        local_plans = self._state.list_meal_plans()
        plan_ids_by_date: dict[str, list[int]] = {}
        globally_tracked_row_ids: set[int] = set()
        for plan in local_plans:
            plan_id = plan.get("plan_id")
            entries = plan.get("entries")
            if not isinstance(plan_id, int) or not isinstance(entries, list):
                continue
            for instance in self._state.get_meal_plan_instance_sync(plan_id).values():
                if isinstance(instance, dict):
                    row_id = instance.get("meal_plan_row_id")
                    if isinstance(row_id, int):
                        globally_tracked_row_ids.add(row_id)
            for entry in entries:
                if isinstance(entry, dict):
                    extra_recipes = entry.get("extra_recipes")
                    if isinstance(extra_recipes, list):
                        for extra in extra_recipes:
                            row_id = extra.get("tandoor_meal_plan_row_id") if isinstance(extra, dict) else None
                            if isinstance(row_id, int):
                                globally_tracked_row_ids.add(row_id)
                entry_date = entry.get("date") if isinstance(entry, dict) else None
                if isinstance(entry_date, str):
                    plan_ids_by_date.setdefault(entry_date, []).append(plan_id)

        changed_plan_ids: list[int] = []
        changed_dates: set[str] = set()
        shopping_stale_plan_ids: list[int] = []
        stale_shopping_recipe_ids: set[int] = set()

        for plan in local_plans:
            plan_id = plan.get("plan_id")
            entries = plan.get("entries")
            if not isinstance(plan_id, int) or not isinstance(entries, list):
                continue

            plan_changed = False
            plan_shopping_stale = False
            tracked_sync = self._state.get_meal_plan_instance_sync(plan_id)
            normalized_entries, entry_id_remap = self._merge_duplicate_date_entries(entries)
            if normalized_entries != entries:
                entries = normalized_entries
                plan_changed = True
            if entry_id_remap:
                remapped_sync: dict[str, dict[str, Any]] = {}
                for instance_key, instance in tracked_sync.items():
                    if not isinstance(instance, dict):
                        continue
                    next_instance = dict(instance)
                    entry_id = next_instance.get("entry_id")
                    if isinstance(entry_id, int) and entry_id in entry_id_remap:
                        next_instance["entry_id"] = entry_id_remap[entry_id]
                        recipe_id = next_instance.get("recipe_id")
                        role = str(next_instance.get("role") or "primary")
                        if isinstance(recipe_id, int):
                            instance_key = self._instance_key_for_recipe(
                                entry_id=entry_id_remap[entry_id],
                                role=role,
                                recipe_id=recipe_id,
                                slot_index=next_instance.get("slot_index")
                                if isinstance(next_instance.get("slot_index"), int)
                                else None,
                            )
                        else:
                            instance_key = self._instance_key_for_mode(
                                entry_id=entry_id_remap[entry_id],
                                mode=str(next_instance.get("purpose") or "empty"),
                            )
                        next_instance["instance_key"] = instance_key
                        plan_changed = True
                    remapped_sync[instance_key] = next_instance
                tracked_sync = remapped_sync
            tracked_by_row_id: dict[int, dict[str, Any]] = {}
            for instance in tracked_sync.values():
                if not isinstance(instance, dict):
                    continue
                row_id = instance.get("meal_plan_row_id")
                if isinstance(row_id, int):
                    tracked_by_row_id[row_id] = instance

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("entry_id")
                entry_date = entry.get("date")
                if not isinstance(entry_id, int) or not isinstance(entry_date, str):
                    continue

                instance_rows = [
                    (instance_key, row)
                    for instance_key, instance in tracked_sync.items()
                    if isinstance(instance, dict)
                    and instance.get("entry_id") == entry_id
                    and isinstance(instance.get("meal_plan_row_id"), int)
                    for row in [rows_by_instance.get(instance_key)]
                    if isinstance(row, dict)
                ]
                tracked_instance_keys = {
                    instance_key
                    for instance_key, instance in tracked_sync.items()
                    if isinstance(instance, dict) and instance.get("entry_id") == entry_id
                }
                for instance_key, remote_row in instance_rows:
                    remote_recipe = remote_row.get("recipe")
                    recipe_id = remote_recipe.get("id") if isinstance(remote_recipe, dict) else remote_recipe
                    recipe_title = (
                        remote_recipe.get("name") or remote_recipe.get("title")
                        if isinstance(remote_recipe, dict)
                        else remote_row.get("title")
                    )
                    next_recipe = None
                    if isinstance(recipe_id, int):
                        next_recipe = {
                            "id": recipe_id,
                            "title": str(recipe_title or f"Recipe {recipe_id}"),
                            "url": self._recipe_url(recipe_id),
                        }
                    if entry.get("recipe") != next_recipe or entry.get("servings") != remote_row.get("servings"):
                        for instance_key, instance in tracked_sync.items():
                            if instance_key in {key for key, _ in instance_rows} and isinstance(instance, dict):
                                shopping_recipe_id = instance.get("shopping_recipe_id")
                                if isinstance(shopping_recipe_id, int):
                                    stale_shopping_recipe_ids.add(shopping_recipe_id)
                        entry["recipe"] = next_recipe
                        entry["servings"] = remote_row.get("servings")
                        remote_date = str(remote_row.get("from_date") or "").split("T", 1)[0]
                        if remote_date and remote_date != entry_date:
                            entry["date"] = remote_date
                            start_date = plan.get("start_date")
                            if isinstance(start_date, str):
                                try:
                                    entry["day_index"] = (date.fromisoformat(remote_date) - date.fromisoformat(start_date)).days
                                except ValueError:
                                    pass
                        plan_changed = True
                        plan_shopping_stale = True
                        changed_dates.add(entry_date)
                    instance = tracked_sync.get(instance_key)
                    if isinstance(instance, dict) and isinstance(recipe_id, int):
                        next_instance_key = self._instance_key_for_recipe(
                            entry_id=entry_id,
                            role=str(instance.get("role") or "primary"),
                            recipe_id=recipe_id,
                            slot_index=instance.get("slot_index") if isinstance(instance.get("slot_index"), int) else None,
                        )
                        next_instance = dict(instance)
                        next_instance["instance_key"] = next_instance_key
                        previous_recipe_id = instance.get("recipe_id")
                        next_instance["recipe_id"] = recipe_id
                        next_instance["recipe_title"] = str(recipe_title or f"Recipe {recipe_id}")
                        next_instance["servings"] = int(remote_row.get("servings") or entry.get("servings") or 2)
                        if previous_recipe_id != recipe_id:
                            next_instance["shopping_recipe_id"] = None
                            next_instance["shopping_activated"] = False
                        if next_instance_key != instance_key:
                            tracked_sync.pop(instance_key, None)
                        tracked_sync[next_instance_key] = next_instance

                for instance_key in tracked_instance_keys:
                    instance = tracked_sync.get(instance_key)
                    row_id = instance.get("meal_plan_row_id") if isinstance(instance, dict) else None
                    if instance_key in rows_by_instance or (isinstance(row_id, int) and row_id in rows_by_id):
                        continue
                    if not isinstance(instance, dict):
                        continue
                    if isinstance(instance.get("meal_plan_row_id"), int):
                        shopping_recipe_id = instance.get("shopping_recipe_id")
                        if isinstance(shopping_recipe_id, int):
                            stale_shopping_recipe_ids.add(shopping_recipe_id)
                        entry["recipe"] = None
                        entry["mode"] = "empty"
                        entry["extra_recipes"] = []
                        instance["meal_plan_row_id"] = None
                        instance["shopping_recipe_id"] = None
                        instance["shopping_activated"] = False
                        plan_changed = True
                        plan_shopping_stale = True
                        changed_dates.add(entry_date)

                extra_recipes = entry.get("extra_recipes")
                if isinstance(extra_recipes, list):
                    extra_recipes_before = len(extra_recipes)
                    retained_extras: list[Any] = []
                    for extra in extra_recipes:
                        if not isinstance(extra, dict) or extra.get("source") != "tandoor":
                            retained_extras.append(extra)
                            continue
                        row_id = extra.get("tandoor_meal_plan_row_id")
                        remote_row = rows_by_id.get(row_id) if isinstance(row_id, int) else None
                        if not isinstance(remote_row, dict):
                            for instance in tracked_sync.values():
                                if isinstance(instance, dict) and instance.get("meal_plan_row_id") == row_id:
                                    shopping_recipe_id = instance.get("shopping_recipe_id")
                                    if isinstance(shopping_recipe_id, int):
                                        stale_shopping_recipe_ids.add(shopping_recipe_id)
                            continue

                        remote_recipe = remote_row.get("recipe")
                        recipe_id = remote_recipe.get("id") if isinstance(remote_recipe, dict) else remote_recipe
                        if not isinstance(recipe_id, int):
                            retained_extras.append(extra)
                            continue
                        recipe_title = (
                            remote_recipe.get("name") or remote_recipe.get("title")
                            if isinstance(remote_recipe, dict)
                            else remote_row.get("title")
                        )
                        next_extra = dict(extra)
                        next_extra["recipe"] = {
                            "id": recipe_id,
                            "title": str(recipe_title or f"Recipe {recipe_id}"),
                            "url": self._recipe_url(recipe_id),
                        }
                        if extra.get("recipe") != next_extra["recipe"]:
                            plan_changed = True
                            plan_shopping_stale = True
                            changed_dates.add(entry_date)
                        retained_extras.append(next_extra)
                        for instance_key, instance in tracked_sync.items():
                            if not isinstance(instance, dict) or instance.get("meal_plan_row_id") != row_id:
                                continue
                            if instance.get("recipe_id") != recipe_id or instance.get("servings") != remote_row.get("servings"):
                                shopping_recipe_id = instance.get("shopping_recipe_id")
                                if isinstance(shopping_recipe_id, int):
                                    stale_shopping_recipe_ids.add(shopping_recipe_id)
                                instance["recipe_id"] = recipe_id
                                instance["recipe_title"] = str(recipe_title or f"Recipe {recipe_id}")
                                instance["servings"] = int(remote_row.get("servings") or entry.get("servings") or 2)
                                if plan_id == min(plan_ids_by_date.get(entry_date, [plan_id])):
                                    plan_changed = True
                                    plan_shopping_stale = True
                                    changed_dates.add(entry_date)
                    extra_recipes[:] = retained_extras
                    if len(extra_recipes) != extra_recipes_before:
                        plan_changed = True
                        plan_shopping_stale = True
                        changed_dates.add(entry_date)

                for remote_row in rows_by_date.get(entry_date, []):
                    row_id = remote_row.get("id")
                    if not isinstance(row_id, int) or row_id in globally_tracked_row_ids:
                        continue
                    if plan_id != min(plan_ids_by_date.get(entry_date, [plan_id])):
                        continue
                    remote_recipe = remote_row.get("recipe")
                    recipe_id = remote_recipe.get("id") if isinstance(remote_recipe, dict) else remote_recipe
                    if not isinstance(recipe_id, int):
                        continue
                    recipe_title = (
                        remote_recipe.get("name") or remote_recipe.get("title")
                        if isinstance(remote_recipe, dict)
                        else remote_row.get("title")
                    )
                    extra_recipes = entry.get("extra_recipes")
                    if not isinstance(extra_recipes, list):
                        extra_recipes = []
                        entry["extra_recipes"] = extra_recipes
                    already_present = any(
                        isinstance(extra, dict) and extra.get("tandoor_meal_plan_row_id") == row_id
                        for extra in extra_recipes
                    )
                    if already_present:
                        continue
                    extra_recipes.append(
                        {
                            "recipe": {
                                "id": recipe_id,
                                "title": str(recipe_title or f"Recipe {recipe_id}"),
                                "url": self._recipe_url(recipe_id),
                            },
                            "purpose": "tandoor",
                            "source": "tandoor",
                            "tandoor_meal_plan_row_id": row_id,
                        }
                    )
                    plan_changed = True
                    if plan_id == min(plan_ids_by_date.get(entry_date, [plan_id])):
                        plan_shopping_stale = True
                        changed_dates.add(entry_date)

                    instance_key = self._instance_key_for_recipe(
                        entry_id=entry_id,
                        role="extra",
                        recipe_id=recipe_id,
                        slot_index=len(extra_recipes) - 1,
                    )
                    tracked_sync[instance_key] = {
                        "instance_key": instance_key,
                        "entry_id": entry_id,
                        "recipe_id": recipe_id,
                        "recipe_title": str(recipe_title or f"Recipe {recipe_id}"),
                        "role": "extra",
                        "slot_index": len(extra_recipes) - 1,
                        "purpose": "tandoor",
                        "date": entry_date,
                        "servings": int(remote_row.get("servings") or entry.get("servings") or 2),
                        "meal_plan_row_id": row_id,
                        "shopping_recipe_id": None,
                        "shopping_activated": False,
                    }
                    globally_tracked_row_ids.add(row_id)

            if plan_changed:
                self._state.update_meal_plan(plan_id, {"entries": entries})
                self._state.set_meal_plan_instance_sync(plan_id, tracked_sync)
                changed_plan_ids.append(plan_id)
            if plan_shopping_stale:
                shopping_stale_plan_ids.append(plan_id)

        shopping_sync: list[dict[str, Any]] = []
        if ensure_tandoor_writes_enabled is not None and build_shopping_view is not None:
            for shopping_recipe_id in sorted(stale_shopping_recipe_ids):
                await self._remove_instance_shopping_entries(shopping_recipe_id)
            for plan_id in shopping_stale_plan_ids:
                try:
                    result = await self.generate_shopping_from_plan(
                        plan_id=plan_id,
                        mode="sync",
                        ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                        build_shopping_view=build_shopping_view,
                        sync_meal_plan_rows=False,
                    )
                    shopping_sync.append(
                        {
                            "plan_id": plan_id,
                            "status": "synchronized",
                            "created_count": result["data"].get("created_count", 0),
                            "failed_count": result["data"].get("failed_count", 0),
                        }
                    )
                except (HTTPException, TandoorError) as exc:
                    shopping_sync.append(
                        {"plan_id": plan_id, "status": "stale", "error": str(exc)}
                    )

        return {
            "source": "tandoor+local-state",
            "revision": self._state.current_revision(),
            "changed_plan_ids": sorted(changed_plan_ids),
            "changed_dates": sorted(changed_dates),
            "shopping_stale_plan_ids": sorted(shopping_stale_plan_ids),
            "shopping_sync": shopping_sync,
        }

    def _remote_meal_plan_row_matches(self, remote: dict[str, Any], desired: dict[str, Any]) -> bool:
        remote_recipe = remote.get("recipe")
        remote_recipe_id = remote_recipe.get("id") if isinstance(remote_recipe, dict) else remote_recipe
        remote_date = str(remote.get("from_date") or "").split("T", 1)[0]
        return (
            remote_recipe_id == desired.get("recipe_id")
            and remote_date == desired.get("date")
            and remote.get("servings") == desired.get("servings")
        )

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
            title = str(instance.get("recipe_title") or f"Recipe {recipe_id}")
        elif isinstance(mode_label, str):
            title = mode_label
        else:
            title = "Meal"

        payload = {
            "title": title,
            "servings": servings,
            "from_date": iso_date,
            "to_date": iso_date,
            "meal_type": meal_type_payload,
            "addshopping": False,
            "note": (
                f"wfd-plan:{instance['plan_token']};"
                f"wfd-instance:{instance['instance_key']}"
            ),
        }
        if isinstance(recipe_id, int):
            payload["recipe"] = recipe_id
        result = await self._client.create_meal_plan(payload)
        row_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(row_id, int) or row_id < 1:
            raise TandoorError("Tandoor meal-plan create did not return an id.")
        return row_id

    async def _update_meal_plan_row_for_instance(self, row_id: int, instance: dict[str, Any]) -> None:
        """Update one known Tandoor row without changing its upstream identity."""
        recipe_id = instance.get("recipe_id")
        servings = instance.get("servings")
        from_date = instance.get("date")
        plan_token = instance.get("plan_token")
        instance_key = instance.get("instance_key")
        if (
            not isinstance(servings, int)
            or not isinstance(from_date, str)
            or not isinstance(plan_token, str)
            or not isinstance(instance_key, str)
        ):
            raise TandoorError("Cannot update meal-plan row: instance is missing required fields.")

        payload: dict[str, Any] = {
            "servings": servings,
            "from_date": f"{from_date}T18:00:00Z",
            "to_date": f"{from_date}T18:00:00Z",
            "note": f"wfd-plan:{plan_token};wfd-instance:{instance_key}",
        }
        if isinstance(recipe_id, int):
            payload["recipe"] = recipe_id
        await self._client.update_meal_plan(row_id, payload)

    def _serialize_instance_sync(self, instance_sync: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        serialized: dict[str, dict[str, Any]] = {}
        for instance_key, row in instance_sync.items():
            serialized[instance_key] = {
                "instance_key": str(row.get("instance_key") or instance_key),
                "entry_id": int(row.get("entry_id") or 0),
                "recipe_id": int(row.get("recipe_id")) if isinstance(row.get("recipe_id"), int) else None,
                "recipe_title": str(row.get("recipe_title")) if isinstance(row.get("recipe_title"), str) else None,
                "role": str(row.get("role") or "primary"),
                "slot_index": row.get("slot_index") if isinstance(row.get("slot_index"), int) else None,
                "purpose": str(row.get("purpose")) if row.get("purpose") is not None else None,
                "date": str(row.get("date") or ""),
                "servings": int(row.get("servings")),
                "meal_plan_row_id": row.get("meal_plan_row_id")
                if isinstance(row.get("meal_plan_row_id"), int) and int(row.get("meal_plan_row_id")) > 0
                else None,
                "shopping_recipe_id": row.get("shopping_recipe_id")
                if isinstance(row.get("shopping_recipe_id"), int) and int(row.get("shopping_recipe_id")) > 0
                else None,
                "shopping_activated": bool(row.get("shopping_activated", False)),
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
        plan_token = self._ensure_plan_token(plan_id, plan_payload)
        for desired_row in desired_sync.values():
            desired_row["plan_token"] = plan_token
        pending_operation_ids = self._pending_operation_ids_for_plan(plan_id)
        remote_by_instance = (
            await self._remote_meal_plan_rows_by_instance()
            if pending_operation_ids
            else {}
        )

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
            retained_row["shopping_recipe_id"] = None
            retained_row["shopping_activated"] = False
            retained_removed_sync[instance_key] = retained_row

        next_sync: dict[str, dict[str, Any]] = dict(retained_removed_sync)

        for instance_key in sorted(desired_sync.keys()):
            desired_row = dict(desired_sync[instance_key])
            previous_row = previous_sync.get(instance_key)
            remote_row = remote_by_instance.get(
                f"wfd-plan:{plan_token};wfd-instance:{instance_key}"
            )

            if isinstance(remote_row, dict):
                remote_row_id = remote_row.get("id")
                if self._remote_meal_plan_row_matches(remote_row, desired_row) and isinstance(remote_row_id, int):
                    desired_row["meal_plan_row_id"] = remote_row_id
                    if isinstance(previous_row, dict) and previous_row.get("meal_plan_row_id") == remote_row_id:
                        desired_row["shopping_recipe_id"] = previous_row.get("shopping_recipe_id")
                        desired_row["shopping_activated"] = bool(previous_row.get("shopping_activated", False))
                    next_sync[instance_key] = desired_row
                    continue
                if isinstance(remote_row_id, int):
                    await self._update_meal_plan_row_for_instance(remote_row_id, desired_row)
                    desired_row["meal_plan_row_id"] = remote_row_id
                    next_sync[instance_key] = desired_row
                    continue

            if isinstance(previous_row, dict):
                unchanged = (
                    previous_row.get("recipe_id") == desired_row.get("recipe_id")
                    and previous_row.get("recipe_title") == desired_row.get("recipe_title")
                    and int(previous_row.get("servings")) == int(desired_row.get("servings"))
                    and str(previous_row.get("date") or "") == str(desired_row.get("date") or "")
                )
                previous_row_id = previous_row.get("meal_plan_row_id")
                if unchanged and isinstance(previous_row_id, int):
                    desired_row["meal_plan_row_id"] = previous_row_id
                    desired_row["shopping_recipe_id"] = previous_row.get("shopping_recipe_id")
                    desired_row["shopping_activated"] = bool(previous_row.get("shopping_activated", False))
                    next_sync[instance_key] = desired_row
                    continue

                if isinstance(previous_row_id, int):
                    await self._update_meal_plan_row_for_instance(previous_row_id, desired_row)
                    desired_row["meal_plan_row_id"] = previous_row_id
                    desired_row["shopping_recipe_id"] = None
                    desired_row["shopping_activated"] = False
                    next_sync[instance_key] = desired_row
                    continue

            created_row_id = await self._create_meal_plan_row_for_instance(desired_row)
            desired_row["meal_plan_row_id"] = created_row_id
            desired_row["shopping_recipe_id"] = None
            desired_row["shopping_activated"] = False
            next_sync[instance_key] = desired_row

        serializable_sync = self._serialize_instance_sync(next_sync)
        self._state.set_meal_plan_instance_sync(plan_id, serializable_sync)
        self._state.delete_pending_projections(pending_operation_ids)

    async def _delete_all_tandoor_meal_plan_rows(
        self,
        *,
        plan_id: int,
        previous_sync: dict[str, dict[str, Any]] | None = None,
        ensure_tandoor_writes_enabled,
        operation_name: str,
    ) -> None:
        ensure_tandoor_writes_enabled(operation_name)
        sync_rows = previous_sync if previous_sync is not None else self._state.get_meal_plan_instance_sync(plan_id)
        for _, value in sync_rows.items():
            if not isinstance(value, dict):
                continue
            row_id = value.get("meal_plan_row_id")
            await self._delete_meal_plan_row_if_present(row_id)

    async def retry_pending_projection(self, operation_id: str, ensure_tandoor_writes_enabled) -> dict[str, Any]:
        """Retry one durable Tandoor projection and clear it after success."""
        pending = self._state.pending_projection(operation_id)
        if pending is None or pending.get("domain") != "meal_plan":
            raise HTTPException(status_code=404, detail="Pending meal-plan projection not found.")
        payload = pending.get("payload")
        plan_id = payload.get("plan_id") if isinstance(payload, dict) else None
        if not isinstance(plan_id, int):
            raise HTTPException(status_code=409, detail="Pending meal-plan projection has no plan_id.")

        try:
            if pending.get("operation") == "delete_plan":
                previous_sync = payload.get("instance_sync")
                await self._delete_all_tandoor_meal_plan_rows(
                    plan_id=plan_id,
                    previous_sync=previous_sync if isinstance(previous_sync, dict) else {},
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_retry_delete",
                )
                self._state.delete_pending_projections({operation_id})
                return self._response("local-state", {"deleted": True, "plan_id": plan_id})

            plan = self._state.get_meal_plan(plan_id)
            if plan is None:
                raise HTTPException(status_code=409, detail="Pending meal plan no longer exists.")
            await self._sync_tandoor_meal_plan_rows(
                plan_id=plan_id,
                plan_payload=plan,
                ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                operation_name="meal_plan_retry_projection",
            )
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return self._response("tandoor+local-state", self._enrich_plan_recipe_urls(plan))

    async def _canonical_plan_response(self, plan_id: int) -> dict[str, Any]:
        """Reread Tandoor and return the resulting authoritative plan projection."""
        await self.sync_from_tandoor()
        plan = self._state.get_meal_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Meal plan is absent from the canonical projection.")
        response_plan = self._enrich_plan_recipe_urls(plan)
        entries = response_plan.get("entries") if isinstance(response_plan, dict) else None
        if isinstance(response_plan, dict):
            response_plan["entry_count"] = len(entries) if isinstance(entries, list) else 0
        return self._response("tandoor-projection", response_plan)

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
        """Generate, persist, and project a new rule-aware meal plan."""
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

        unique_candidates: list[dict[str, Any]] = []
        seen_candidate_ids: set[int] = set()
        for candidate in recipe_candidates:
            candidate_id = candidate.get("id")
            if not isinstance(candidate_id, int) or candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            unique_candidates.append(candidate)
        recipe_candidates = unique_candidates

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
            "plan_token": uuid.uuid4().hex,
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
                self._state.delete_meal_plan(int(stored["plan_id"]))
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        self._state.append_sync_event("meal_plan_generated", stored)
        if ensure_tandoor_writes_enabled is not None:
            return await self._canonical_plan_response(int(stored["plan_id"]))
        return self._response("local-state", self._enrich_plan_recipe_urls(stored))

    async def patch_plan(self, plan_id: int, payload: dict[str, Any], ensure_tandoor_writes_enabled=None) -> dict:
        """Patch one plan under its per-plan lock and synchronize its rows."""
        if "entries" in payload:
            raise HTTPException(
                status_code=400,
                detail="Bulk meal-plan entry replacement is not supported; mutate one entry at a time.",
            )
        lock = self._get_plan_mutation_lock(plan_id)
        async with lock:
            current = self._state.get_meal_plan(plan_id)
            if current is None:
                raise HTTPException(status_code=404, detail="Meal plan not found.")
            previous_sync = self._state.get_meal_plan_instance_sync(plan_id)

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
                    self._state.update_meal_plan(plan_id, current)
                    self._state.set_meal_plan_instance_sync(plan_id, previous_sync)
                    raise HTTPException(status_code=502, detail=str(exc)) from exc

            self._state.append_sync_event("meal_plan_updated", {"plan_id": plan_id, "payload": payload})
            if ensure_tandoor_writes_enabled is not None:
                return await self._canonical_plan_response(plan_id)
            return self._response("local-state", self._enrich_plan_recipe_urls(updated))

    async def add_entry(self, plan_id: int, payload: dict[str, Any], ensure_tandoor_writes_enabled=None) -> dict:
        """Append an entry locally, then project the changed plan upstream."""
        lock = self._get_plan_mutation_lock(plan_id)
        async with lock:
            plan = self._state.get_meal_plan(plan_id)
            if plan is None:
                raise HTTPException(status_code=404, detail="Meal plan not found.")
            previous_sync = self._state.get_meal_plan_instance_sync(plan_id)
            previous_plan = deepcopy(plan)

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
                    self._state.update_meal_plan(plan_id, previous_plan)
                    self._state.set_meal_plan_instance_sync(plan_id, previous_sync)
                    raise HTTPException(status_code=502, detail=str(exc)) from exc

            self._state.append_sync_event("meal_plan_entry_added", {"plan_id": plan_id, "entry": entry})

            if ensure_tandoor_writes_enabled is not None:
                return await self._canonical_plan_response(plan_id)
            return self._response("local-state", self._enrich_plan_recipe_urls(updated))

    async def patch_entry(
        self,
        plan_id: int,
        entry_id: int,
        payload: dict[str, Any],
        ensure_tandoor_writes_enabled=None,
    ) -> dict:
        lock = self._get_plan_mutation_lock(plan_id)
        async with lock:
            plan = self._state.get_meal_plan(plan_id)
            if plan is None:
                raise HTTPException(status_code=404, detail="Meal plan not found.")
            previous_plan = deepcopy(plan)
            previous_sync = self._state.get_meal_plan_instance_sync(plan_id)

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

            if "mode" not in payload and isinstance(payload.get("recipe"), dict):
                entry["mode"] = "planned"

            next_mode = str(entry.get("mode") or "planned")
            if next_mode in {"leftover", "takeout", "empty"}:
                entry["recipe"] = None
                entry["extra_recipes"] = []

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
                    self._state.update_meal_plan(plan_id, previous_plan)
                    self._state.set_meal_plan_instance_sync(plan_id, previous_sync)
                    raise HTTPException(status_code=502, detail=str(exc)) from exc

            self._state.append_sync_event(
                "meal_plan_entry_updated",
                {"plan_id": plan_id, "entry_id": entry_id, "payload": payload},
            )

            if ensure_tandoor_writes_enabled is not None:
                return await self._canonical_plan_response(plan_id)
            return self._response("local-state", self._enrich_plan_recipe_urls(updated))

    async def delete_entry(self, plan_id: int, entry_id: int, ensure_tandoor_writes_enabled=None) -> dict:
        lock = self._get_plan_mutation_lock(plan_id)
        async with lock:
            plan = self._state.get_meal_plan(plan_id)
            if plan is None:
                raise HTTPException(status_code=404, detail="Meal plan not found.")
            previous_plan = deepcopy(plan)
            previous_sync = self._state.get_meal_plan_instance_sync(plan_id)

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
                    self._state.update_meal_plan(plan_id, previous_plan)
                    self._state.set_meal_plan_instance_sync(plan_id, previous_sync)
                    raise HTTPException(status_code=502, detail=str(exc)) from exc

            self._state.append_sync_event("meal_plan_entry_deleted", {"plan_id": plan_id, "entry_id": entry_id})

            if ensure_tandoor_writes_enabled is not None:
                return await self._canonical_plan_response(plan_id)
            return self._response("local-state", updated)

    async def delete_plan(self, plan_id: int, ensure_tandoor_writes_enabled=None) -> dict:
        plan = self._state.get_meal_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        if ensure_tandoor_writes_enabled is not None:
            ensure_tandoor_writes_enabled("meal_plan_delete")

        if ensure_tandoor_writes_enabled is not None:
            try:
                await self._delete_all_tandoor_meal_plan_rows(
                    plan_id=plan_id,
                    previous_sync=self._state.get_meal_plan_instance_sync(plan_id),
                    ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                    operation_name="meal_plan_delete",
                )
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        deleted = self._state.delete_meal_plan(plan_id)
        if deleted is None:
            raise HTTPException(status_code=404, detail="Meal plan not found.")

        self._state.append_sync_event("meal_plan_deleted", {"plan_id": plan_id})
        return self._response("local-state", {"deleted": True, "plan_id": plan_id})

    def _build_bulk_entries_from_recipe_payload(self, recipe_payload: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen_ingredient_ids: set[int] = set()

        def collect(items: Any) -> None:
            if not isinstance(items, list):
                return
            for ingredient in items:
                if not isinstance(ingredient, dict):
                    continue

                ingredient_id = ingredient.get("id")
                amount = ingredient.get("amount")
                food = ingredient.get("food")
                unit = ingredient.get("unit")

                if not isinstance(ingredient_id, int) or ingredient_id < 1:
                    continue
                if ingredient_id in seen_ingredient_ids:
                    continue
                if not isinstance(amount, (int, float)):
                    continue
                if not isinstance(food, dict) or not isinstance(food.get("id"), int):
                    continue
                if bool(food.get("ignore_shopping", False)):
                    continue
                if not isinstance(unit, dict) or not isinstance(unit.get("id"), int):
                    continue

                seen_ingredient_ids.add(ingredient_id)
                entries.append(
                    {
                        "amount": amount,
                        "unit_id": int(unit["id"]),
                        "food_id": int(food["id"]),
                        "ingredient_id": ingredient_id,
                    }
                )

        collect(recipe_payload.get("ingredients"))
        steps = recipe_payload.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                collect(step.get("ingredients"))

        return entries

    async def _activate_instance_shopping(
        self,
        *,
        instance_key: str,
        meal_plan_row_id: int,
        recipe_id: int,
        servings: int,
    ) -> tuple[int, int]:
        recipe_payload = await self._client.get_recipe(recipe_id)
        if not isinstance(recipe_payload, dict):
            raise TandoorError(f"Recipe payload is invalid for recipe_id={recipe_id}.")

        shopping_recipe_payload = {
            "recipe": recipe_id,
            "mealplan": meal_plan_row_id,
            "servings": servings,
            "name": "",
        }
        created_shopping_recipe = await self._client.create_shopping_list_from_recipe(shopping_recipe_payload)
        shopping_recipe_id = (
            created_shopping_recipe.get("id") if isinstance(created_shopping_recipe, dict) else None
        )
        if not isinstance(shopping_recipe_id, int) or shopping_recipe_id < 1:
            raise TandoorError(
                f"Tandoor did not return shopping-list-recipe id for instance {instance_key}."
            )

        bulk_entries = self._build_bulk_entries_from_recipe_payload(recipe_payload)
        if len(bulk_entries) > 0:
            await self._client.bulk_create_shopping_list_recipe_entries(
                shopping_recipe_id,
                {
                    "entries": bulk_entries,
                    "shopping_lists_ids": [],
                },
            )

        return shopping_recipe_id, len(bulk_entries)

    async def _remove_instance_shopping_entries(self, shopping_recipe_id: int | None) -> None:
        """Remove shopping rows previously generated for one recipe instance."""
        if not isinstance(shopping_recipe_id, int) or shopping_recipe_id < 1:
            return
        payload = await self._client.list_shopping_entries(limit=500)
        for entry in self._extract_results(payload):
            if entry.get("shopping_recipe_id") != shopping_recipe_id:
                continue
            entry_id = entry.get("id")
            if isinstance(entry_id, int):
                await self._delete_shopping_entry_if_present(entry_id)

    async def _delete_shopping_entry_if_present(self, entry_id: int) -> None:
        """Delete one generated shopping row while tolerating an upstream deletion."""
        try:
            await self._client.delete_shopping_entry(entry_id)
        except TandoorError as exc:
            if not self._is_not_found_error(exc):
                raise

    async def generate_shopping_from_plan(
        self,
        *,
        plan_id: int,
        mode: str = "sync",
        ensure_tandoor_writes_enabled,
        build_shopping_view,
        sync_meal_plan_rows: bool = False,
    ) -> dict:
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
            # Also acquire the meal plan mutation lock to prevent concurrent mutations
            plan_lock = self._get_plan_mutation_lock(plan_id)
            async with plan_lock:
                ensure_tandoor_writes_enabled("meal_plan_to_shopping_list")
                plan = self._state.get_meal_plan(plan_id)
                if plan is None:
                    raise HTTPException(status_code=404, detail="Meal plan not found.")

                entries = plan.get("entries")
                if not isinstance(entries, list):
                    entries = []

                # Refresh the cached projection before deriving shopping entries.
                if sync_meal_plan_rows:
                    await self.sync_from_tandoor()
                    plan = self._state.get_meal_plan(plan_id)
                    if plan is None:
                        raise HTTPException(status_code=404, detail="Meal plan not found.")
                    entries = plan.get("entries")
                    if not isinstance(entries, list):
                        entries = []

                created: list[dict[str, Any]] = []
                failed: list[dict[str, Any]] = []

                previous_sync = normalize_previous_instance_sync()
                desired_sync = self._desired_instance_sync(plan, entries)
                next_sync: dict[str, dict[str, Any]] = {}
                recipe_source = "regenerate_missing" if mode == "regenerate_missing" else "sync"

                for instance_key in sorted(desired_sync.keys()):
                    desired_row = dict(desired_sync[instance_key])
                    previous_row = previous_sync.get(instance_key)

                    row_changed = False
                    if isinstance(previous_row, dict):
                        desired_row["meal_plan_row_id"] = previous_row.get("meal_plan_row_id")
                        desired_row["shopping_recipe_id"] = previous_row.get("shopping_recipe_id")
                        desired_row["shopping_activated"] = bool(previous_row.get("shopping_activated", False))
                        row_changed = (
                            int(previous_row.get("servings")) != int(desired_row.get("servings"))
                            or str(previous_row.get("date") or "") != str(desired_row.get("date") or "")
                            or previous_row.get("recipe_id") != desired_row.get("recipe_id")
                        )

                    meal_plan_row_id = desired_row.get("meal_plan_row_id")
                    if not isinstance(meal_plan_row_id, int) or meal_plan_row_id < 1:
                        if sync_meal_plan_rows:
                            failed.append(
                                {
                                    "operation": "shopping_generation",
                                    "recipe_source": recipe_source,
                                    "instance_key": instance_key,
                                    "recipe_id": desired_row.get("recipe_id"),
                                    "errors": ["Meal-plan row is absent from the canonical Tandoor projection."],
                                }
                            )
                            continue
                        desired_row["plan_token"] = self._ensure_plan_token(plan_id, plan)
                        meal_plan_row_id = await self._create_meal_plan_row_for_instance(desired_row)
                        desired_row["meal_plan_row_id"] = meal_plan_row_id
                        desired_row["shopping_recipe_id"] = None
                        desired_row["shopping_activated"] = False
                        row_changed = True

                    if (
                        row_changed
                        or not isinstance(desired_row.get("shopping_recipe_id"), int)
                        or mode == "regenerate_missing"
                    ):
                        await self._remove_instance_shopping_entries(
                            desired_row.get("shopping_recipe_id")
                            if isinstance(previous_row, dict)
                            else None
                        )
                        desired_row["shopping_recipe_id"] = None
                        desired_row["shopping_activated"] = False

                    shopping_recipe_id = desired_row.get("shopping_recipe_id")
                    shopping_activated = bool(desired_row.get("shopping_activated", False))
                    should_activate = False
                    if mode == "regenerate_missing":
                        should_activate = True
                    else:
                        should_activate = (
                            row_changed
                            or not isinstance(shopping_recipe_id, int)
                            or not shopping_activated
                        )

                    recipe_id = desired_row.get("recipe_id")
                    servings = desired_row.get("servings")
                    if should_activate and isinstance(recipe_id, int) and isinstance(servings, int):
                        try:
                            activated_shopping_recipe_id, bulk_count = await self._activate_instance_shopping(
                                instance_key=instance_key,
                                meal_plan_row_id=meal_plan_row_id,
                                recipe_id=recipe_id,
                                servings=servings,
                            )
                        except TandoorError as exc:
                            failed.append(
                                {
                                    "operation": "recipe_shopping_update",
                                    "recipe_source": recipe_source,
                                    "instance_key": instance_key,
                                    "recipe_id": recipe_id,
                                    "payload": {"servings": servings, "mealplan": meal_plan_row_id},
                                    "errors": [str(exc)],
                                }
                            )
                            if isinstance(previous_row, dict):
                                next_sync[instance_key] = dict(previous_row)
                            continue

                        desired_row["shopping_recipe_id"] = activated_shopping_recipe_id
                        desired_row["shopping_activated"] = True
                        created.append(
                            {
                                "operation": "recipe_shopping_update",
                                "recipe_source": recipe_source,
                                "instance_key": instance_key,
                                "recipe_id": recipe_id,
                                "payload": {"servings": servings, "mealplan": meal_plan_row_id},
                                "result": {
                                    "shopping_recipe_id": activated_shopping_recipe_id,
                                    "bulk_entries_created": bulk_count,
                                },
                            }
                        )

                    next_sync[instance_key] = desired_row

                return await finalize_generation(
                    plan_id=plan_id,
                    mode=mode,
                    next_sync=next_sync,
                    created=created,
                    failed=failed,
                )
