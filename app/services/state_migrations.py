from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from app.models.state_schema import (
    CURRENT_STATE_SCHEMA_VERSION,
    Stage2StateDocument,
)
from app.services.sync_event_compaction import compact_sync_event_payload


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


def _migrate_v3_to_v4(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = deepcopy(payload)

    raw_archive = next_payload.get("archive")
    archive = raw_archive if isinstance(raw_archive, dict) else {}

    meal_plan_archive = archive.get("meal_plans")
    if not isinstance(meal_plan_archive, list):
        meal_plan_archive = []

    sync_archive = archive.get("sync_events")
    if not isinstance(sync_archive, list):
        sync_archive = []

    archive["meal_plans"] = meal_plan_archive
    archive["sync_events"] = sync_archive
    next_payload["archive"] = archive

    raw_events = next_payload.get("shopping_sync_events")
    if isinstance(raw_events, list):
        compacted_events: list[dict[str, Any]] = []
        for raw_event in raw_events:
            if not isinstance(raw_event, dict):
                continue
            compacted_events.append(
                {
                    "cursor": raw_event.get("cursor"),
                    "operation": str(raw_event.get("operation") or ""),
                    "payload": compact_sync_event_payload(
                        str(raw_event.get("operation") or ""),
                        raw_event.get("payload"),
                    ),
                    "created_at": raw_event.get("created_at"),
                }
            )
        next_payload["shopping_sync_events"] = compacted_events

    next_payload["schema_version"] = 4
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
        payload = _migrate_v3_to_v4(payload)
        schema_version = payload.get("schema_version")

    if schema_version != CURRENT_STATE_SCHEMA_VERSION:
        raise StateSchemaError(
            "Unsupported state schema_version "
            f"{schema_version}. Expected {CURRENT_STATE_SCHEMA_VERSION}."
        )

    try:
        document = Stage2StateDocument.model_validate(payload)
    except ValidationError as exc:
        raise StateSchemaError(f"Invalid stage2 state payload: {exc}") from exc

    return document.model_dump(mode="python")
