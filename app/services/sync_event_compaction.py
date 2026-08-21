from __future__ import annotations

from typing import Any


def _updated_fields(payload: Any, key: str) -> list[str]:
    patch = payload.get(key) if isinstance(payload, dict) else None
    return sorted(list(patch.keys())) if isinstance(patch, dict) else []


def compact_sync_event_payload(operation: str, payload: Any) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}

    if operation == "meal_plan_entry_deleted":
        return {"plan_id": source.get("plan_id"), "entry_id": source.get("entry_id")}

    if operation in {"meal_plan_deleted", "shopping_entry_deleted"}:
        key = "plan_id" if operation == "meal_plan_deleted" else "entry_id"
        return {key: source.get(key)}

    if operation == "meal_plan_generated":
        return {
            "plan_id": source.get("plan_id"),
            "start_date": source.get("start_date"),
            "length_days": source.get("length_days"),
            "diners": source.get("diners"),
            "entry_count": len(source.get("entries")) if isinstance(source.get("entries"), list) else 0,
        }

    if operation == "meal_plan_updated":
        return {"plan_id": source.get("plan_id"), "updated_fields": _updated_fields(source, "payload")}

    if operation == "meal_plan_entry_added":
        entry_payload = source.get("entry") if isinstance(source.get("entry"), dict) else {}
        recipe = entry_payload.get("recipe") if isinstance(entry_payload.get("recipe"), dict) else {}
        return {
            "plan_id": source.get("plan_id"),
            "entry_id": entry_payload.get("entry_id"),
            "day_index": entry_payload.get("day_index"),
            "date": entry_payload.get("date"),
            "mode": entry_payload.get("mode"),
            "recipe_id": recipe.get("id"),
        }

    if operation == "meal_plan_entry_updated":
        return {
            "plan_id": source.get("plan_id"),
            "entry_id": source.get("entry_id"),
            "updated_fields": _updated_fields(source, "payload"),
        }

    if operation == "shopping_entry_created":
        return {"entry_id": source.get("id"), "status": source.get("status"), "source": source.get("source")}

    if operation == "shopping_entry_updated":
        return {
            "entry_id": source.get("entry_id"),
            "status": source.get("status"),
            "updated_fields": _updated_fields(source, "request"),
        }

    if operation == "meal_plan_shopping_generated":
        return {
            "plan_id": source.get("plan_id"),
            "mode": source.get("mode"),
            "created_count": source.get("created_count"),
            "failed_count": source.get("failed_count"),
        }

    return source
