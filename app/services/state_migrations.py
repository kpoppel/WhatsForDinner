from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any
import uuid

from pydantic import ValidationError

from app.models.state_schema import (
    CURRENT_STATE_SCHEMA_VERSION,
    ServerStateDocument,
)


class StateSchemaError(ValueError):
    """Raised when Stage2 state is invalid for the configured schema."""


def _migrate_v1_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    if not isinstance(next_payload.get("meal_plan_instance_sync"), dict):
        next_payload["meal_plan_instance_sync"] = {}
    next_payload["schema_version"] = 2
    return next_payload


def _migrate_v2_to_v3(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    plan_sync = next_payload.get("meal_plan_instance_sync")
    if isinstance(plan_sync, dict):
        for _, plan_value in plan_sync.items():
            if not isinstance(plan_value, dict):
                continue
            instances = plan_value.get("instances")
            if not isinstance(instances, dict):
                continue
            for _, instance_row in instances.items():
                if not isinstance(instance_row, dict):
                    continue
                instance_row.pop("entry_ids", None)

    next_payload["schema_version"] = 3
    return next_payload


def _migrate_v4_to_v5(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    if not isinstance(next_payload.get("derived_state_revision"), int):
        next_payload["derived_state_revision"] = 0
    if not isinstance(next_payload.get("recipe_use_history"), list):
        next_payload["recipe_use_history"] = []
    if not isinstance(next_payload.get("pending_projections"), dict):
        next_payload["pending_projections"] = {}
    next_payload["schema_version"] = 5
    return next_payload


def _migrate_v5_to_v6(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    meal_plans = next_payload.get("meal_plans")
    if isinstance(meal_plans, dict):
        for plan in meal_plans.values():
            if not isinstance(plan, dict):
                continue
            plan_token = plan.get("plan_token")
            if not isinstance(plan_token, str) or not plan_token:
                plan["plan_token"] = uuid.uuid4().hex
    next_payload["schema_version"] = 6
    return next_payload


def _migrate_v6_to_v7(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    for key in (
        "archive",
        "shopping_sync_events",
        "next_sync_event_id",
        "derived_state_revision",
    ):
        next_payload.pop(key, None)
    next_payload["schema_version"] = 7
    return next_payload


def _migrate_v7_to_v8(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    next_payload.pop("pending_projections", None)
    next_payload["shopping_snapshot"] = []
    next_payload["pending_shopping_changes"] = {}
    next_payload["schema_version"] = 8
    return next_payload


def _migrate_v8_to_v9(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    next_payload.pop("shopping_snapshot", None)
    next_payload["schema_version"] = 9
    return next_payload


def _migrate_v9_to_v10(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    overrides = next_payload.get("shopping_status_overrides")
    if isinstance(overrides, dict):
        next_payload["shopping_status_overrides"] = {
            key: value
            for key, value in overrides.items()
            if isinstance(key, str) and key.startswith("-")
        }
    next_payload["schema_version"] = 10
    return next_payload


def _migrate_v10_to_v11(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    history = next_payload["recipe_use_history"]
    existing_uses = {
        (item["recipe_id"], item["used_date"], item["plan_id"], item["entry_id"])
        for item in history
        if isinstance(item, dict)
    }
    meal_plans = next_payload["meal_plans"]
    for raw_plan_id, plan in meal_plans.items():
        if not isinstance(plan, dict):
            continue
        try:
            plan_id = int(raw_plan_id)
        except ValueError:
            continue
        entries = plan.get("entries")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("entry_id")
            used_date = entry.get("date")
            if not isinstance(entry_id, int) or not isinstance(used_date, str):
                continue
            try:
                date.fromisoformat(used_date)
            except ValueError:
                continue
            recipes = [entry.get("recipe")]
            extra_recipes = entry.get("extra_recipes")
            if isinstance(extra_recipes, list):
                recipes.extend(extra_recipes)
            for recipe in recipes:
                if not isinstance(recipe, dict):
                    continue
                recipe_id = recipe.get("id")
                if not isinstance(recipe_id, int):
                    continue
                recipe_use = (recipe_id, used_date, plan_id, entry_id)
                if recipe_use in existing_uses:
                    continue
                history.append(
                    {
                        "recipe_id": recipe_id,
                        "used_date": used_date,
                        "plan_id": plan_id,
                        "entry_id": entry_id,
                    }
                )
                existing_uses.add(recipe_use)
    next_payload["schema_version"] = 11
    return next_payload


def _migrate_v11_to_v12(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    plan_sync = next_payload.get("meal_plan_instance_sync")
    if isinstance(plan_sync, dict):
        for plan_value in plan_sync.values():
            if not isinstance(plan_value, dict):
                continue
            instances = plan_value.get("instances")
            if not isinstance(instances, dict):
                continue
            for instance_row in instances.values():
                if not isinstance(instance_row, dict):
                    continue
                for field in (
                    "instance_key",
                    "entry_id",
                    "recipe_id",
                    "role",
                    "slot_index",
                    "purpose",
                    "shopping_activated",
                ):
                    instance_row.pop(field, None)
    next_payload["schema_version"] = 12
    return next_payload


def _migrate_v12_to_v13(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    plan_sync = next_payload.pop("meal_plan_instance_sync", {})
    meal_plans = next_payload.get("meal_plans")
    if isinstance(plan_sync, dict) and isinstance(meal_plans, dict):
        for plan_id, sync in plan_sync.items():
            plan = meal_plans.get(plan_id)
            if isinstance(plan, dict) and isinstance(sync, dict):
                plan["tandoor_sync"] = sync
    next_payload["schema_version"] = 13
    return next_payload


def _migrate_v13_to_v14(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    meal_plans = next_payload.get("meal_plans")
    if isinstance(meal_plans, dict):
        for plan in meal_plans.values():
            if not isinstance(plan, dict):
                continue
            tandoor_sync = plan.get("tandoor_sync")
            if not isinstance(tandoor_sync, dict):
                continue
            instances = tandoor_sync.get("instances")
            if not isinstance(instances, dict):
                continue
            for instance in instances.values():
                if not isinstance(instance, dict):
                    continue
                instance.pop("recipe_title", None)
                instance.pop("date", None)
                instance.pop("servings", None)
    next_payload["schema_version"] = 14
    return next_payload


def _migrate_v14_to_v15(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    meal_plans = next_payload.get("meal_plans")
    if not isinstance(meal_plans, dict):
        next_payload["schema_version"] = 15
        return next_payload

    for plan in meal_plans.values():
        if not isinstance(plan, dict):
            continue
        entries = plan.get("entries")
        legacy_sync = plan.pop("tandoor_sync", None)
        if not isinstance(entries, list) or not isinstance(legacy_sync, dict):
            continue
        instances = legacy_sync.get("instances")
        if not isinstance(instances, dict):
            continue

        entries_by_id = {
            entry.get("entry_id"): entry
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("entry_id"), int)
        }
        for instance_key, sync in instances.items():
            if not isinstance(instance_key, str) or not isinstance(sync, dict):
                continue
            meal_plan_row_id = sync.get("meal_plan_row_id")
            shopping_recipe_id = sync.get("shopping_recipe_id")
            if not isinstance(meal_plan_row_id, int) or meal_plan_row_id < 1:
                continue
            embedded_sync = {
                "meal_plan_row_id": meal_plan_row_id,
                "shopping_recipe_id": shopping_recipe_id
                if isinstance(shopping_recipe_id, int) and shopping_recipe_id > 0
                else None,
            }
            parts = instance_key.split(":")
            if len(parts) < 4 or parts[0] != "entry":
                continue
            try:
                entry = entries_by_id.get(int(parts[1]))
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            if (
                len(parts) == 4
                and parts[2] == "mode"
                and parts[3] in {"leftover", "takeout", "empty"}
                and entry.get("mode") == parts[3]
                and not isinstance(entry.get("recipe"), dict)
            ):
                entry["tandoor_sync"] = embedded_sync
                continue
            if len(parts) == 5 and parts[2] == "primary" and parts[3] == "recipe":
                try:
                    recipe_id = int(parts[4])
                except ValueError:
                    continue
                recipe = entry.get("recipe")
                if isinstance(recipe, dict) and recipe.get("id") == recipe_id:
                    recipe["tandoor_sync"] = embedded_sync
                continue
            if len(parts) == 6 and parts[2] == "extra" and parts[4] == "recipe":
                try:
                    slot_index = int(parts[3])
                    recipe_id = int(parts[5])
                except ValueError:
                    continue
                extra_recipes = entry.get("extra_recipes")
                if not isinstance(extra_recipes, list) or slot_index < 0 or slot_index >= len(extra_recipes):
                    continue
                extra_recipe = extra_recipes[slot_index]
                recipe = extra_recipe.get("recipe") if isinstance(extra_recipe, dict) else None
                if isinstance(recipe, dict) and recipe.get("id") == recipe_id:
                    recipe["tandoor_sync"] = embedded_sync

    next_payload["schema_version"] = 15
    return next_payload


def _migrate_v15_to_v16(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    meal_plans = next_payload.get("meal_plans")
    if isinstance(meal_plans, dict):
        for plan in meal_plans.values():
            if not isinstance(plan, dict):
                continue
            entries = plan.get("entries")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                recipes: list[dict[str, Any]] = []
                primary_recipe = entry.pop("recipe", None)
                if isinstance(primary_recipe, dict):
                    primary_recipe["purpose"] = "meal"
                    recipes.append(primary_recipe)
                extra_recipes = entry.pop("extra_recipes", [])
                if isinstance(extra_recipes, list):
                    for extra_recipe in extra_recipes:
                        if not isinstance(extra_recipe, dict):
                            continue
                        recipe = extra_recipe.get("recipe")
                        if not isinstance(recipe, dict):
                            continue
                        recipe["purpose"] = (
                            "shopping_only" if extra_recipe.get("purpose") == "shopping_only" else "meal"
                        )
                        recipes.append(recipe)
                entry["recipes"] = recipes
    next_payload["schema_version"] = 16
    return next_payload


def _migrate_v16_to_v17(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)
    if not isinstance(next_payload.get("pending_meal_plan_changes"), dict):
        next_payload["pending_meal_plan_changes"] = {}
    next_payload["schema_version"] = 17
    return next_payload


def migrate_and_validate_state(raw: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(raw)

    schema_version = payload.get("schema_version")
    if schema_version is None:
        payload["schema_version"] = 1
        schema_version = 1

    if schema_version == 1:
        payload = _migrate_v1_to_v2(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 2:
        payload = _migrate_v2_to_v3(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 3:
        payload["schema_version"] = 4
        schema_version = 4

    if schema_version == 4:
        payload = _migrate_v4_to_v5(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 5:
        payload = _migrate_v5_to_v6(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 6:
        payload = _migrate_v6_to_v7(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 7:
        payload = _migrate_v7_to_v8(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 8:
        payload = _migrate_v8_to_v9(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 9:
        payload = _migrate_v9_to_v10(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 10:
        payload = _migrate_v10_to_v11(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 11:
        payload = _migrate_v11_to_v12(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 12:
        payload = _migrate_v12_to_v13(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 13:
        payload = _migrate_v13_to_v14(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 14:
        payload = _migrate_v14_to_v15(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 15:
        payload = _migrate_v15_to_v16(payload)
        schema_version = payload.get("schema_version")

    if schema_version == 16:
        payload = _migrate_v16_to_v17(payload)
        schema_version = payload.get("schema_version")

    if schema_version != CURRENT_STATE_SCHEMA_VERSION:
        raise StateSchemaError(
            "Unsupported state schema_version "
            f"{schema_version}. Expected {CURRENT_STATE_SCHEMA_VERSION}."
        )

    try:
        document = ServerStateDocument.model_validate(payload)
    except ValidationError as exc:
        raise StateSchemaError(f"Invalid stage2 state payload: {exc}") from exc

    return document.model_dump(mode="python")
