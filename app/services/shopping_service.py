"""Shopping-list domain operations across Tandoor and local overlays.

The service translates app statuses and metadata to Tandoor operations, applies
offline batches serially, and returns canonical views plus revision and pending
projection state for browser reconciliation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import HTTPException

from app.services.stage2_state import Stage2State
from app.services.tandoor_client import TandoorClient, TandoorError

SHOPPING_STATUSES = {"remaining", "skipped", "completed"}


class ShoppingService:
    """Coordinate shopping mutations, offline batches, and canonical reads."""

    def __init__(self, state: Stage2State, tandoor_client: TandoorClient) -> None:
        self._state = state
        self._client = tandoor_client
        self._sync_lock = asyncio.Lock()

    def _response(
        self,
        source: str,
        data: Any,
        cursor: int | None = None,
        projection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = {
            "source": source,
            "revision": self._state.current_revision(),
            "projection": projection or {"status": "synchronized"},
            "pending_projections": self._state.pending_projections(),
            "data": data,
        }
        if cursor is not None:
            response["cursor"] = cursor
        return response

    async def get_view(
        self,
        *,
        limit: int,
        extract_results: Callable[[Any], list[dict[str, Any]]],
        build_shopping_view: Callable[[list[dict[str, Any]]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Load Tandoor entries, merge local overlays, and return a canonical view."""
        try:
            data = await self._client.list_shopping_entries(limit=limit)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        entries = extract_results(data)
        view = build_shopping_view(entries)

        return self._response(
            "tandoor+local-state",
            view,
            cursor=self._state.current_sync_cursor(),
        )

    async def create_entry(
        self,
        payload: dict[str, Any],
        ensure_tandoor_writes_enabled: Callable[[str], None],
        extract_reminder_patch: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
        build_local_entry_payload: Callable[[int, dict[str, Any]], dict[str, Any]],
        status_to_tandoor_fields: Callable[[str], dict[str, Any]],
        operation_name: str,
    ) -> dict[str, Any]:
        """Create either a local ad-hoc item or a Tandoor-backed shopping entry."""
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
            cursor = self._state.append_sync_event("shopping_entry_created", stored)
            return self._response("local-state", stored, cursor=cursor)

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

        cursor = self._state.append_sync_event("shopping_entry_created", created)
        return self._response("tandoor+local-state", created, cursor=cursor)

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
        """Apply a validated patch to local storage or Tandoor and record the event."""
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

            cursor = self._state.append_sync_event(
                "shopping_entry_updated",
                {
                    "entry_id": entry_id,
                    "request": payload,
                    "data": updated_local,
                    "status": status,
                },
            )
            response = self._response("local-state", updated_local, cursor=cursor)
            response["effective_status"] = str(updated_local.get("status") or "remaining")
            return response

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

        cursor = self._state.append_sync_event(
            "shopping_entry_updated",
            {
                "entry_id": entry_id,
                "request": payload,
                "data": updated,
                "status": status,
            },
        )

        effective = status or effective_status(
            updated if isinstance(updated, dict) else {}, self._state.get_shopping_statuses()
        )

        response = self._response("tandoor+local-state", updated, cursor=cursor)
        response["effective_status"] = effective
        return response

    async def delete_entry(
        self,
        entry_id: int,
        ensure_tandoor_writes_enabled: Callable[[str], None],
        operation_name: str,
    ) -> dict[str, Any]:
        """Delete a local item or upstream entry and clear its derived overlays."""
        deleted_local = self._state.delete_local_shopping_entry(entry_id)
        if deleted_local is not None:
            self._state.delete_shopping_status(entry_id)
            self._state.delete_shopping_item_metadata(entry_id)
            cursor = self._state.append_sync_event("shopping_entry_deleted", {"entry_id": entry_id})
            return self._response("local-state", {"deleted": entry_id}, cursor=cursor)

        ensure_tandoor_writes_enabled(operation_name)
        try:
            deleted = await self._client.delete_shopping_entry(entry_id)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        self._state.delete_shopping_status(entry_id)
        self._state.delete_shopping_item_metadata(entry_id)
        cursor = self._state.append_sync_event("shopping_entry_deleted", {"entry_id": entry_id})
        return self._response("tandoor+local-state", deleted, cursor=cursor)

    async def apply_sync_changes(
        self,
        changes: list[dict[str, Any]],
        ensure_tandoor_writes_enabled: Callable[[str], None],
        extract_reminder_patch: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
        build_local_entry_payload: Callable[[int, dict[str, Any]], dict[str, Any]],
        local_store_group_payload: Callable[[Any], dict[str, Any]],
        status_to_tandoor_fields: Callable[[str], dict[str, Any]],
        effective_status: Callable[[dict[str, Any], dict[str, str]], str],
        extract_results: Callable[[Any], list[dict[str, Any]]],
        build_shopping_view: Callable[[list[dict[str, Any]]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Serialize offline mutations, classify rejections, and rehydrate canonical data."""
        async with self._sync_lock:
            applied: list[dict[str, Any]] = []
            rejected: list[dict[str, Any]] = []

            for idx, change in enumerate(changes):
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
                                "cursor": result.get("cursor"),
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
                                "cursor": result.get("cursor"),
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
                                "cursor": result.get("cursor"),
                                "operation": operation,
                                "data": result.get("data"),
                            }
                        )
                    else:
                        rejected.append({"index": idx, "reason": f"Unsupported operation: {operation}"})
                except (TandoorError, ValueError, HTTPException) as exc:
                    rejected.append({"index": idx, "reason": str(exc)})

            try:
                shopping_payload = await self._client.list_shopping_entries(limit=500)
            except TandoorError as exc:
                pending = self._state.create_pending_projection(
                    "shopping",
                    "reconcile_sync",
                    {"changes": changes},
                    str(exc),
                )
                return {
                    "server_cursor": self._state.current_sync_cursor(),
                    "revision": self._state.current_revision(),
                    "cursor": self._state.current_sync_cursor(),
                    "data": None,
                    "projection": pending,
                    "pending_projections": self._state.pending_projections(),
                    "applied": applied,
                    "rejected": rejected,
                }

            view = build_shopping_view(extract_results(shopping_payload))
            return {
                "server_cursor": self._state.current_sync_cursor(),
                "revision": self._state.current_revision(),
                "cursor": self._state.current_sync_cursor(),
                "data": view,
                "pending_projections": self._state.pending_projections(),
                "applied": applied,
                "rejected": rejected,
            }

    async def retry_pending_reconciliation(
        self,
        operation_id: str,
        extract_results: Callable[[Any], list[dict[str, Any]]],
        build_shopping_view: Callable[[list[dict[str, Any]]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Retry a failed canonical read and clear its projection marker on success."""
        pending = self._state.pending_projection(operation_id)
        if (
            pending is None
            or pending.get("domain") != "shopping"
            or pending.get("operation") != "reconcile_sync"
        ):
            raise HTTPException(status_code=404, detail="Pending shopping reconciliation not found.")
        try:
            shopping_payload = await self._client.list_shopping_entries(limit=500)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        self._state.delete_pending_projections({operation_id})
        return self._response(
            "tandoor+local-state",
            build_shopping_view(extract_results(shopping_payload)),
            cursor=self._state.current_sync_cursor(),
        )
