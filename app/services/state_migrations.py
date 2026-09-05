"""Sequential migrations and strict validation for persisted application state.

Migrations operate on deep copies and only move one known schema version at a
time. The final Pydantic validation is the persistence contract; unsupported or
invalid documents fail rather than being silently reshaped.
"""

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
    """Add per-instance sync storage while preserving the v1 input."""
    next_payload = deepcopy(payload)
    if not isinstance(next_payload.get("meal_plan_instance_sync"), dict):
        next_payload["meal_plan_instance_sync"] = {}
    next_payload["schema_version"] = 2
    return next_payload


def _migrate_v2_to_v3(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove obsolete entry ID arrays from v2 instance records."""
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
    """Add archives and compact historical sync events for schema v4."""
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


def _migrate_v4_to_v5(payload: dict[str, Any]) -> dict[str, Any]:
    """Add revision, recipe-history, and pending-projection fields for v5."""
    next_payload = deepcopy(payload)
    if not isinstance(next_payload.get("derived_state_revision"), int):
        next_payload["derived_state_revision"] = 0
    if not isinstance(next_payload.get("recipe_use_history"), list):
        next_payload["recipe_use_history"] = []
    if not isinstance(next_payload.get("pending_projections"), dict):
        next_payload["pending_projections"] = {}
    next_payload["schema_version"] = 5
    return next_payload


def migrate_and_validate_state(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate a state document to the current version and return validated data."""

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

    if schema_version == 4:
        payload = _migrate_v4_to_v5(payload)
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
