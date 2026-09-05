"""Persisted-state schema, migration, atomic-write, and recovery tests."""

import json
from datetime import datetime, timezone

import pytest

from app.services.stage2_state import Stage2State
from app.services.state_migrations import StateSchemaError


def test_stage2_state_writes_schema_version(tmp_path) -> None:
    """Verify first-run state is initialized at the current schema version."""
    state = Stage2State(str(tmp_path))

    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    assert payload["schema_version"] == 5
    assert payload["archive"] == {"meal_plans": [], "sync_events": []}
    assert payload["derived_state_revision"] == 0
    assert payload["recipe_use_history"] == []
    assert payload["pending_projections"] == {}


def test_stage2_state_invalid_payload_fails_fast(tmp_path) -> None:
    """Verify invalid persisted state is rejected instead of reshaped silently."""
    state = Stage2State(str(tmp_path))

    invalid_payload = {
        "schema_version": 4,
        "selected_keyword_ids": [],
        "meal_plan_rules": {"no_repeat_days": "bad"},
        "user_settings": {
            "default_diners": 2,
            "default_notification_time": "08:00",
        },
        "meal_plans": {},
        "next_meal_plan_id": 1,
        "next_entry_id": 1,
        "shopping_status_overrides": {},
        "shopping_item_metadata": {},
        "local_shopping_entries": {},
        "next_local_shopping_entry_id": -1,
        "meal_plan_instance_sync": {},
        "shopping_sync_events": [],
        "next_sync_event_id": 1,
        "archive": {"meal_plans": [], "sync_events": []},
    }
    state.state_file.write_text(json.dumps(invalid_payload), encoding="utf-8")

    with pytest.raises(StateSchemaError):
        state.selected_keywords()


def test_stage2_state_sync_event_retention_by_max_count(tmp_path) -> None:
    """Verify oldest sync events are pruned and archived by count."""
    state = Stage2State(str(tmp_path), sync_event_max_count=2, sync_event_max_age_days=365)

    state.append_sync_event("event_a", {"v": 1})
    state.append_sync_event("event_b", {"v": 2})
    state.append_sync_event("event_c", {"v": 3})

    events = state.sync_events_since(0)
    assert [int(event["cursor"]) for event in events] == [2, 3]


def test_stage2_state_sync_event_retention_by_max_age(tmp_path) -> None:
    """Verify stale sync events are pruned according to configured age."""
    state = Stage2State(str(tmp_path), sync_event_max_count=10, sync_event_max_age_days=1)

    state.append_sync_event("event_old", {"v": 1})
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    payload["shopping_sync_events"][0]["created_at"] = "2000-01-01T00:00:00+00:00"
    with state.state_file.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=True)

    new_cursor = state.append_sync_event("event_new", {"v": 2})
    events = state.sync_events_since(0)

    assert len(events) == 1
    assert int(events[0]["cursor"]) == new_cursor
    assert isinstance(events[0].get("created_at"), str)
    parsed_new = datetime.fromisoformat(events[0]["created_at"].replace("Z", "+00:00"))
    assert parsed_new.tzinfo is not None
    assert parsed_new.astimezone(timezone.utc).year >= 2026


def test_stage2_state_migrates_v1_payload_to_v4(tmp_path) -> None:
    """Verify legacy v1 state migrates through the current schema chain."""
    state = Stage2State(str(tmp_path))

    legacy_payload = {
        "schema_version": 1,
        "selected_keyword_ids": [],
        "meal_plan_rules": {"no_repeat_days": 30},
        "user_settings": {
            "default_diners": 2,
            "default_notification_time": "08:00",
        },
        "meal_plans": {},
        "next_meal_plan_id": 1,
        "next_entry_id": 1,
        "shopping_status_overrides": {},
        "shopping_item_metadata": {},
        "local_shopping_entries": {},
        "next_local_shopping_entry_id": -1,
        "shopping_sync_events": [],
        "next_sync_event_id": 1,
    }
    state.state_file.write_text(json.dumps(legacy_payload), encoding="utf-8")

    assert state.selected_keywords() == []
    state.set_selected_keywords([])
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    assert payload["schema_version"] == 5
    assert payload["meal_plan_instance_sync"] == {}
    assert payload["archive"] == {"meal_plans": [], "sync_events": []}


def test_stage2_state_migrates_v2_payload_and_strips_entry_ids(tmp_path) -> None:
    """Verify v2 instance rows lose the obsolete entry_ids field."""
    state = Stage2State(str(tmp_path))

    v2_payload = {
        "schema_version": 2,
        "selected_keyword_ids": [],
        "meal_plan_rules": {"no_repeat_days": 30},
        "user_settings": {
            "default_diners": 2,
            "default_notification_time": "08:00",
        },
        "meal_plans": {},
        "next_meal_plan_id": 1,
        "next_entry_id": 1,
        "shopping_status_overrides": {},
        "shopping_item_metadata": {},
        "local_shopping_entries": {},
        "next_local_shopping_entry_id": -1,
        "meal_plan_instance_sync": {
            "1": {
                "instances": {
                    "entry:1:primary:recipe:11": {
                        "instance_key": "entry:1:primary:recipe:11",
                        "entry_id": 1,
                        "recipe_id": 11,
                        "role": "primary",
                        "slot_index": None,
                        "purpose": "meal",
                        "date": "2026-08-10",
                        "servings": 2,
                        "entry_ids": [100, 101],
                        "meal_plan_row_id": 5,
                        "shopping_recipe_id": 7,
                        "shopping_activated": True,
                    }
                }
            }
        },
        "shopping_sync_events": [],
        "next_sync_event_id": 1,
    }
    state.state_file.write_text(json.dumps(v2_payload), encoding="utf-8")

    assert state.selected_keywords() == []
    state.set_selected_keywords([])
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    assert payload["schema_version"] == 5
    instance = payload["meal_plan_instance_sync"]["1"]["instances"]["entry:1:primary:recipe:11"]
    assert "entry_ids" not in instance


def test_stage2_state_migrates_v3_payload_to_v4_with_archive_defaults(tmp_path) -> None:
    """Verify v3 migration creates archive collections and compacts events."""
    state = Stage2State(str(tmp_path))

    v3_payload = {
        "schema_version": 3,
        "selected_keyword_ids": [],
        "meal_plan_rules": {"no_repeat_days": 30},
        "user_settings": {
            "default_diners": 2,
            "default_notification_time": "08:00",
        },
        "meal_plans": {},
        "next_meal_plan_id": 1,
        "next_entry_id": 1,
        "shopping_status_overrides": {},
        "shopping_item_metadata": {},
        "local_shopping_entries": {},
        "next_local_shopping_entry_id": -1,
        "meal_plan_instance_sync": {},
        "shopping_sync_events": [
            {
                "cursor": 1,
                "operation": "meal_plan_generated",
                "payload": {
                    "plan_id": 4,
                    "start_date": "2026-08-20",
                    "length_days": 2,
                    "diners": 2,
                    "entries": [{"entry_id": 1}, {"entry_id": 2}],
                },
                "created_at": None,
            }
        ],
        "next_sync_event_id": 2,
    }
    state.state_file.write_text(json.dumps(v3_payload), encoding="utf-8")

    assert state.selected_keywords() == []
    state.set_selected_keywords([])
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    assert payload["schema_version"] == 5
    assert payload["archive"] == {"meal_plans": [], "sync_events": []}
    compact_payload = payload["shopping_sync_events"][0]["payload"]
    assert compact_payload["plan_id"] == 4
    assert compact_payload["entry_count"] == 2
    assert "entries" not in compact_payload


def test_stage2_state_migrates_v4_phase05_fields(tmp_path) -> None:
    """Verify v4 migration adds revision, history, and projection defaults."""
    state = Stage2State(str(tmp_path))

    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    payload["schema_version"] = 4
    payload.pop("derived_state_revision", None)
    payload.pop("recipe_use_history", None)
    payload.pop("pending_projections", None)
    state.state_file.write_text(json.dumps(payload), encoding="utf-8")

    state.set_selected_keywords([])

    with state.state_file.open("r", encoding="utf-8") as fp:
        migrated = json.load(fp)
    assert migrated["schema_version"] == 5
    assert migrated["recipe_use_history"] == []
    assert migrated["pending_projections"] == {}


def test_stage2_state_records_recipe_uses_after_plan_deletion(tmp_path) -> None:
    """Verify recipe-use history remains available after plan deletion."""
    state = Stage2State(str(tmp_path))
    plan = state.create_meal_plan(
        {
            "start_date": "2026-09-05",
            "length_days": 1,
            "entries": [
                {
                    "entry_id": 1,
                    "date": "2026-09-05",
                    "recipe": {"id": 42, "title": "Soup"},
                }
            ],
        }
    )

    state.delete_meal_plan(plan["plan_id"])

    assert state.recipe_use_history() == [
        {
            "recipe_id": 42,
            "used_date": "2026-09-05",
            "plan_id": plan["plan_id"],
            "entry_id": 1,
        }
    ]


def test_stage2_state_creates_pending_projection_with_operation_id(tmp_path) -> None:
    """Verify pending projections receive durable unique operation IDs."""
    state = Stage2State(str(tmp_path))

    pending = state.create_pending_projection(
        "meal_plan",
        "patch",
        {"plan_id": 7},
        "Tandoor unavailable",
    )

    assert pending["operation_id"]
    assert pending["status"] == "pending"
    assert state.pending_projections() == [pending]


def test_stage2_state_restores_previous_valid_backup(tmp_path) -> None:
    """Verify backup restoration replaces primary state with validated data."""
    state = Stage2State(str(tmp_path))
    state.set_meal_plan_rules(21)
    state.set_user_settings(6, "17:30")

    assert state.backup_file.is_file()
    assert state.user_settings()["default_diners"] == 6

    state.restore_backup()

    assert state.meal_plan_rules() == {"no_repeat_days": 21}
    assert state.user_settings()["default_diners"] == 2
