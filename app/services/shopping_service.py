from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.services.server_state import ServerState
from fastapi import HTTPException

from app.services.tandoor_client import TandoorClient, TandoorError

SHOPPING_STATUSES = {"remaining", "skipped", "completed"}


class ShoppingService:
    def __init__(self, state: ServerState, tandoor_client: TandoorClient) -> None:
        self._state = state
        self._client = tandoor_client
        self._sync_lock = asyncio.Lock()

    async def get_view(
        self,
        *,
        limit: int,
        extract_results: Callable[[Any], list[dict[str, Any]]],
        build_shopping_view: Callable[[list[dict[str, Any]]], dict[str, Any]],
    ) -> dict[str, Any]:
        data = await self._client.list_shopping_entries(limit=limit)
        entries = extract_results(data)
        source = "tandoor+local-state"
        view = build_shopping_view(entries)

        return {
            "source": source,
            "data": view,
        }

    async def create_entry(
        self,
        payload: dict[str, Any],
        ensure_tandoor_writes_enabled: Callable[[str], None],
        extract_reminder_patch: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
        build_local_entry_payload: Callable[[int, dict[str, Any]], dict[str, Any]],
        status_to_tandoor_fields: Callable[[str], dict[str, Any]],
        operation_name: str,
    ) -> dict[str, Any]:
        request_payload = dict(payload)
        reminder_patch, has_reminder_patch = extract_reminder_patch(request_payload)
        is_ad_hoc = bool(request_payload.pop("ad_hoc", False))

        status = request_payload.pop("status", None)
        status_value: str | None = None
        if status is not None:
            status_value = str(status)
            if status_value not in SHOPPING_STATUSES:
                raise HTTPException(status_code=400, detail="status must be remaining, skipped, or completed.")
        if status_value is None:
            status_value = "remaining"

        if is_ad_hoc:
            local_id = self._state.allocate_local_shopping_entry_id()
            local_entry = build_local_entry_payload(local_id, request_payload)
            local_entry["status"] = status_value
            stored = self._state.set_local_shopping_entry(local_id, local_entry)
            if has_reminder_patch:
                self._state.set_shopping_item_metadata(local_id, reminder_patch)
            self._state.set_shopping_status(local_id, status_value)
            return {
                "source": "local-state",
                "data": stored,
            }

        ensure_tandoor_writes_enabled(operation_name)
        mapped = status_to_tandoor_fields(status_value)
        for key, value in mapped.items():
            request_payload.setdefault(key, value)

        try:
            created = await self._client.create_shopping_entry(request_payload)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        created_id = created.get("id") if isinstance(created, dict) else None
        if isinstance(created_id, int) and has_reminder_patch:
            self._state.set_shopping_item_metadata(created_id, reminder_patch)
        if isinstance(created_id, int):
            self._state.set_shopping_status(created_id, status_value)

        return {
            "source": "tandoor+local-state",
            "data": created,
        }

    async def update_entry(
        self,
        entry_id: int,
        payload: dict[str, Any],
        ensure_tandoor_writes_enabled: Callable[[str], None],
        extract_reminder_patch: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
        local_store_group_payload: Callable[[Any], dict[str, Any]],
        status_to_tandoor_fields: Callable[[str], dict[str, Any]],
        effective_status: Callable[[dict[str, Any], dict[str, str]], str],
        operation_name: str,
    ) -> dict[str, Any]:
        request_payload = dict(payload)
        reminder_patch, has_reminder_patch = extract_reminder_patch(request_payload)

        status = request_payload.pop("status", None)
        if status is not None:
            status = str(status)
            if status not in SHOPPING_STATUSES:
                raise HTTPException(status_code=400, detail="status must be remaining, skipped, or completed.")

            mapped = status_to_tandoor_fields(status)
            for key, value in mapped.items():
                request_payload.setdefault(key, value)

        local_current = self._state.get_local_shopping_entry(entry_id)
        if local_current is not None:
            patch: dict[str, Any] = {}
            if "name" in request_payload:
                raw_name = request_payload["name"]
                if not isinstance(raw_name, str) or not raw_name.strip():
                    raise HTTPException(status_code=400, detail="name must be a non-empty string.")
                patch["name"] = raw_name.strip()
            if "amount" in request_payload:
                raw_amount = request_payload["amount"]
                if not isinstance(raw_amount, (int, float)):
                    raise HTTPException(status_code=400, detail="amount must be numeric.")
                patch["amount"] = raw_amount
            if "unit" in request_payload:
                raw_unit = request_payload["unit"]
                if not isinstance(raw_unit, str):
                    raise HTTPException(status_code=400, detail="unit must be a string.")
                patch["unit"] = raw_unit.strip()
            if "ingredient_type" in request_payload:
                raw_category = request_payload["ingredient_type"]
                if not isinstance(raw_category, str) or not raw_category.strip():
                    raise HTTPException(status_code=400, detail="ingredient_type must be a non-empty string.")
                patch["ingredient_type"] = raw_category.strip()
            if "recipe_context" in request_payload:
                raw_context = request_payload["recipe_context"]
                if not isinstance(raw_context, str) or not raw_context.strip():
                    raise HTTPException(status_code=400, detail="recipe_context must be a non-empty string.")
                patch["recipe_context"] = raw_context.strip()
            if "store_group" in request_payload:
                patch["store_group"] = local_store_group_payload(request_payload["store_group"])
            if status is not None:
                patch["status"] = status

            updated_local = self._state.update_local_shopping_entry(entry_id, patch)
            if updated_local is None:
                raise HTTPException(status_code=404, detail="Shopping list entry not found.")
            if status is not None:
                self._state.set_shopping_status(entry_id, status)
            if has_reminder_patch:
                self._state.set_shopping_item_metadata(entry_id, reminder_patch)

            return {
                "source": "local-state",
                "effective_status": str(updated_local.get("status") or "remaining"),
                "data": updated_local,
            }

        ensure_tandoor_writes_enabled(operation_name)
        if request_payload:
            try:
                updated = await self._client.update_shopping_entry(entry_id, request_payload)
            except TandoorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        else:
            updated = {"id": entry_id}

        if status is not None:
            self._state.set_shopping_status(entry_id, status)
        if has_reminder_patch:
            self._state.set_shopping_item_metadata(entry_id, reminder_patch)

        effective = status or effective_status(
            updated if isinstance(updated, dict) else {}, self._state.get_shopping_statuses()
        )

        return {
            "source": "tandoor+local-state",
            "effective_status": effective,
            "data": updated,
        }

    async def delete_entry(
        self,
        entry_id: int,
        ensure_tandoor_writes_enabled: Callable[[str], None],
        operation_name: str,
    ) -> dict[str, Any]:
        deleted_local = self._state.delete_local_shopping_entry(entry_id)
        if deleted_local is not None:
            self._state.delete_shopping_item_metadata(entry_id)
            return {
                "source": "local-state",
                "data": {"deleted": entry_id},
            }

        ensure_tandoor_writes_enabled(operation_name)
        try:
            deleted = await self._client.delete_shopping_entry(entry_id)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        self._state.delete_shopping_item_metadata(entry_id)
        return {
            "source": "tandoor+local-state",
            "data": deleted,
        }

    async def apply_sync_changes(
        self,
        changes: list[dict[str, Any]],
        ensure_tandoor_writes_enabled: Callable[[str], None],
        extract_reminder_patch: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
        build_local_entry_payload: Callable[[int, dict[str, Any]], dict[str, Any]],
        local_store_group_payload: Callable[[Any], dict[str, Any]],
        status_to_tandoor_fields: Callable[[str], dict[str, Any]],
        effective_status: Callable[[dict[str, Any], dict[str, str]], str],
    ) -> dict[str, Any]:
        async with self._sync_lock:
            applied: list[dict[str, Any]] = []
            rejected: list[dict[str, Any]] = []
            valid_changes: list[dict[str, Any]] = []
            for idx, change in enumerate(changes):
                if not isinstance(change, dict):
                    rejected.append({"index": idx, "reason": "Change must be an object."})
                    continue
                operation = change.get("operation")
                entry_id = change.get("entry_id")
                if operation in {"update", "delete"} and not isinstance(entry_id, int):
                    rejected.append({"index": idx, "reason": "entry_id is required for update"})
                    continue
                valid_changes.append(change)

            self._state.set_pending_shopping_changes(valid_changes)
            changes_to_apply = list(self._state.pending_shopping_changes().values())
            bulk_completed = [
                (idx, change)
                for idx, change in enumerate(changes_to_apply)
                if change.get("operation") == "update"
                and isinstance(change.get("entry_id"), int)
                and change["entry_id"] > 0
                and change.get("payload") == {"status": "completed"}
            ]
            bulk_indexes = {idx for idx, _ in bulk_completed}

            if len(bulk_completed) > 1:
                entry_ids = [change["entry_id"] for _, change in bulk_completed]
                try:
                    await self._client.bulk_update_shopping_entries(entry_ids, checked=True)
                except TandoorError:
                    return {
                        "deferred": True,
                        "applied": [],
                        "rejected": [],
                    }
                for idx, change in bulk_completed:
                    entry_id = change["entry_id"]
                    self._state.set_shopping_status(entry_id, "completed")
                    applied.append(
                        {
                            "index": idx,
                            "operation": "update",
                            "data": {"id": entry_id, "checked": True},
                        }
                    )

            for idx, change in enumerate(changes_to_apply):
                if idx in bulk_indexes and len(bulk_completed) > 1:
                    continue
                if not isinstance(change, dict):
                    rejected.append({"index": idx, "reason": "Change must be an object."})
                    continue

                raw_operation = change.get("operation")
                if isinstance(raw_operation, str):
                    operation = raw_operation.lower()
                else:
                    operation = str(getattr(raw_operation, "value", raw_operation) or "").lower()
                entry_id = change.get("entry_id")
                change_payload = change.get("payload") if isinstance(change.get("payload"), dict) else {}

                try:
                    if operation == "create":
                        result = await self.create_entry(
                            payload=change_payload,
                            ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                            extract_reminder_patch=extract_reminder_patch,
                            build_local_entry_payload=build_local_entry_payload,
                            status_to_tandoor_fields=status_to_tandoor_fields,
                            operation_name="shopping_sync_post_create",
                        )
                        applied.append(
                            {
                                "index": idx,
                                "operation": operation,
                                "data": result.get("data"),
                            }
                        )
                    elif operation == "update":
                        if not isinstance(entry_id, int):
                            raise ValueError("entry_id is required for update")
                        result = await self.update_entry(
                            entry_id=entry_id,
                            payload=change_payload,
                            ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                            extract_reminder_patch=extract_reminder_patch,
                            local_store_group_payload=local_store_group_payload,
                            status_to_tandoor_fields=status_to_tandoor_fields,
                            effective_status=effective_status,
                            operation_name="shopping_sync_post_update",
                        )
                        applied.append(
                            {
                                "index": idx,
                                "operation": operation,
                                "data": result.get("data"),
                            }
                        )
                    elif operation == "delete":
                        if not isinstance(entry_id, int):
                            raise ValueError("entry_id is required for delete")
                        result = await self.delete_entry(
                            entry_id=entry_id,
                            ensure_tandoor_writes_enabled=ensure_tandoor_writes_enabled,
                            operation_name="shopping_sync_post_delete",
                        )
                        applied.append(
                            {
                                "index": idx,
                                "operation": operation,
                                "data": result.get("data"),
                            }
                        )
                    else:
                        rejected.append({"index": idx, "reason": f"Unsupported operation: {operation}"})
                except HTTPException as exc:
                    if exc.status_code == 502:
                        return {
                            "deferred": True,
                            "applied": [],
                            "rejected": [],
                        }
                    rejected.append({"index": idx, "reason": str(exc)})
                except (TandoorError, ValueError) as exc:
                    rejected.append({"index": idx, "reason": str(exc)})

            self._state.clear_pending_shopping_changes()
            return {
                "deferred": False,
                "applied": applied,
                "rejected": rejected,
            }
