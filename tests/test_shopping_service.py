import asyncio
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.services.shopping_service import ShoppingService
from app.services.server_state import ServerState
from app.services.tandoor_client import TandoorError


class FakeShoppingClient:
    def __init__(self) -> None:
        self.created_payloads = []
        self.updated_payloads = []
        self.bulk_updated_payloads = []
        self.deleted_entry_ids = []
        self.next_id = 1

    async def create_shopping_entry(self, payload):
        self.created_payloads.append(dict(payload))
        created = {"id": self.next_id, **dict(payload)}
        self.next_id += 1
        return created

    async def update_shopping_entry(self, entry_id, payload):
        self.updated_payloads.append((entry_id, dict(payload)))
        return {"id": entry_id, **dict(payload)}

    async def delete_shopping_entry(self, entry_id):
        self.deleted_entry_ids.append(entry_id)
        return {"deleted": entry_id}

    async def bulk_update_shopping_entries(self, entry_ids, checked):
        self.bulk_updated_payloads.append((list(entry_ids), checked))
        return {"updated": list(entry_ids)}


class BrokenShoppingClient:
    async def create_shopping_entry(self, payload):
        raise TandoorError("create failed")

    async def update_shopping_entry(self, entry_id, payload):
        raise TandoorError("update failed")

    async def delete_shopping_entry(self, entry_id):
        raise TandoorError("delete failed")


def ensure_writes_enabled(_operation: str) -> None:
    return


def status_to_tandoor_fields(status: str) -> dict:
    if status == "completed":
        return {"checked": True, "delay_until": None}
    if status == "skipped":
        return {"checked": False, "delay_until": (date.today() + timedelta(days=1)).isoformat()}
    return {"checked": False, "delay_until": None}


def extract_reminder_patch(payload: dict) -> tuple[dict, bool]:
    patch = {}
    touched = False
    if "reminder_enabled" in payload:
        patch["reminder_enabled"] = bool(payload.pop("reminder_enabled"))
        touched = True
    if "reminder_date" in payload:
        patch["reminder_date"] = payload.pop("reminder_date")
        touched = True
    return patch, touched


def build_local_entry_payload(entry_id: int, payload: dict) -> dict:
    return {
        "id": entry_id,
        "source": "local",
        "food_id": None,
        "name": str(payload.get("name") or "Unnamed"),
        "amount": payload.get("amount", 0),
        "unit": str(payload.get("unit") or ""),
        "ingredient_type": str(payload.get("ingredient_type") or "Other"),
        "store_group": {"id": None, "name": "General"},
        "recipe": {"id": None, "name": "Unassigned", "image": "", "url": None},
        "recipe_context": str(payload.get("recipe_context") or "Unassigned"),
    }


def local_store_group_payload(raw):
    if isinstance(raw, dict):
        return {"id": raw.get("id"), "name": str(raw.get("name") or "General")}
    return {"id": None, "name": str(raw or "General")}


def effective_status(entry: dict, _overrides: dict[str, str]) -> str:
    if entry.get("checked"):
        return "completed"
    if entry.get("delay_until"):
        return "skipped"
    return "remaining"


def test_create_entry_ad_hoc_persists_local(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    service = ShoppingService(state, FakeShoppingClient())

    result = asyncio.run(
        service.create_entry(
            payload={
                "ad_hoc": True,
                "name": "Ice",
                "amount": 2,
                "status": "skipped",
                "reminder_enabled": True,
                "reminder_date": "2026-08-21",
            },
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            extract_reminder_patch=extract_reminder_patch,
            build_local_entry_payload=build_local_entry_payload,
            status_to_tandoor_fields=status_to_tandoor_fields,
            operation_name="test_create_entry_ad_hoc",
        )
    )

    assert result["source"] == "local-state"
    created = result["data"]
    assert created["id"] < 0
    assert created["status"] == "skipped"

    local_row = state.get_local_shopping_entry(created["id"])
    assert local_row is not None
    assert local_row["name"] == "Ice"
    assert state.get_shopping_statuses()[str(created["id"])] == "skipped"
    assert state.get_shopping_item_metadata()[str(created["id"])]["reminder_enabled"] is True


def test_create_update_delete_remote_roundtrip(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    client = FakeShoppingClient()
    service = ShoppingService(state, client)

    created_result = asyncio.run(
        service.create_entry(
            payload={"food": {"name": "Milk"}, "amount": 1, "status": "completed"},
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            extract_reminder_patch=extract_reminder_patch,
            build_local_entry_payload=build_local_entry_payload,
            status_to_tandoor_fields=status_to_tandoor_fields,
            operation_name="test_create_remote",
        )
    )
    entry_id = created_result["data"]["id"]
    assert created_result["source"] == "tandoor+local-state"
    assert created_result["data"]["checked"] is True
    assert state.get_shopping_statuses() == {}

    updated_result = asyncio.run(
        service.update_entry(
            entry_id=entry_id,
            payload={"status": "skipped"},
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            extract_reminder_patch=extract_reminder_patch,
            local_store_group_payload=local_store_group_payload,
            status_to_tandoor_fields=status_to_tandoor_fields,
            effective_status=effective_status,
            operation_name="test_update_remote",
        )
    )
    assert updated_result["source"] == "tandoor+local-state"
    assert updated_result["effective_status"] == "skipped"
    assert state.get_shopping_statuses() == {}

    deleted_result = asyncio.run(
        service.delete_entry(
            entry_id=entry_id,
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            operation_name="test_delete_remote",
        )
    )
    assert deleted_result["source"] == "tandoor+local-state"
    assert deleted_result["data"]["deleted"] == entry_id


def test_apply_sync_changes_reports_rejected_and_applied(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    service = ShoppingService(state, FakeShoppingClient())

    result = asyncio.run(
        service.apply_sync_changes(
            changes=[
                "bad-change",
                {"operation": "update", "payload": {"status": "completed"}},
                {"operation": "create", "payload": {"ad_hoc": True, "name": "Bread", "amount": 1}},
                {"operation": "delete", "entry_id": -999},
            ],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            extract_reminder_patch=extract_reminder_patch,
            build_local_entry_payload=build_local_entry_payload,
            local_store_group_payload=local_store_group_payload,
            status_to_tandoor_fields=status_to_tandoor_fields,
            effective_status=effective_status,
        )
    )

    assert any(row["operation"] == "create" for row in result["applied"])
    assert any(row["operation"] == "delete" for row in result["applied"])
    reasons = [row["reason"] for row in result["rejected"]]
    assert any("Change must be an object" in reason for reason in reasons)
    assert any("entry_id is required for update" in reason for reason in reasons)


def test_service_wraps_tandoor_errors(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    service = ShoppingService(state, BrokenShoppingClient())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.create_entry(
                payload={"food": {"name": "Milk"}, "amount": 1},
                ensure_tandoor_writes_enabled=ensure_writes_enabled,
                extract_reminder_patch=extract_reminder_patch,
                build_local_entry_payload=build_local_entry_payload,
                status_to_tandoor_fields=status_to_tandoor_fields,
                operation_name="test_create_error",
            )
        )

    assert exc_info.value.status_code == 502


def test_sync_defers_batch_when_tandoor_is_unavailable(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    service = ShoppingService(state, BrokenShoppingClient())

    result = asyncio.run(
        service.apply_sync_changes(
            changes=[{"operation": "update", "entry_id": 3, "payload": {"status": "completed"}}],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            extract_reminder_patch=extract_reminder_patch,
            build_local_entry_payload=build_local_entry_payload,
            local_store_group_payload=local_store_group_payload,
            status_to_tandoor_fields=status_to_tandoor_fields,
            effective_status=effective_status,
        )
    )

    assert result == {"deferred": True, "applied": [], "rejected": []}
    assert state.pending_shopping_changes() == {
        "3": {"operation": "update", "entry_id": 3, "payload": {"status": "completed"}}
    }


def test_sync_retries_existing_deferred_changes(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    state.set_pending_shopping_changes(
        [{"operation": "update", "entry_id": 3, "payload": {"status": "completed"}}]
    )
    client = FakeShoppingClient()
    service = ShoppingService(state, client)

    result = asyncio.run(
        service.apply_sync_changes(
            changes=[],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            extract_reminder_patch=extract_reminder_patch,
            build_local_entry_payload=build_local_entry_payload,
            local_store_group_payload=local_store_group_payload,
            status_to_tandoor_fields=status_to_tandoor_fields,
            effective_status=effective_status,
        )
    )

    assert result["deferred"] is False
    assert client.updated_payloads == [(3, {"checked": True, "delay_until": None})]
    assert state.pending_shopping_changes() == {}


def test_sync_uses_tandoor_bulk_for_completed_items(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    client = FakeShoppingClient()
    service = ShoppingService(state, client)

    result = asyncio.run(
        service.apply_sync_changes(
            changes=[
                {"operation": "update", "entry_id": 3, "payload": {"status": "completed"}},
                {"operation": "update", "entry_id": 4, "payload": {"status": "completed"}},
            ],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            extract_reminder_patch=extract_reminder_patch,
            build_local_entry_payload=build_local_entry_payload,
            local_store_group_payload=local_store_group_payload,
            status_to_tandoor_fields=status_to_tandoor_fields,
            effective_status=effective_status,
        )
    )

    assert result["deferred"] is False
    assert client.bulk_updated_payloads == [([3, 4], True)]
    assert client.updated_payloads == []
