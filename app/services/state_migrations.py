from __future__ import annotations

from copy import deepcopy
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
