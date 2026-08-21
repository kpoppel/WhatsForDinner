import json
from datetime import datetime, timezone

import pytest

from app.services.stage2_state import Stage2State
from app.services.state_migrations import StateSchemaError


def test_stage2_state_writes_schema_version(tmp_path) -> None:
    state = Stage2State(str(tmp_path))

    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    assert payload["schema_version"] == 3


def test_stage2_state_invalid_payload_fails_fast(tmp_path) -> None:
    state = Stage2State(str(tmp_path))

    invalid_payload = {
        "schema_version": 3,
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
    }
    state.state_file.write_text(json.dumps(invalid_payload), encoding="utf-8")

    with pytest.raises(StateSchemaError):
        state.selected_keywords()


def test_stage2_state_sync_event_retention_by_max_count(tmp_path) -> None:
    state = Stage2State(str(tmp_path), sync_event_max_count=2, sync_event_max_age_days=365)

    state.append_sync_event("event_a", {"v": 1})
    state.append_sync_event("event_b", {"v": 2})
    state.append_sync_event("event_c", {"v": 3})

    events = state.sync_events_since(0)
    assert [int(event["cursor"]) for event in events] == [2, 3]


def test_stage2_state_sync_event_retention_by_max_age(tmp_path) -> None:
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


def test_stage2_state_migrates_v1_payload_to_v3(tmp_path) -> None:
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
    assert payload["schema_version"] == 3
    assert payload["meal_plan_instance_sync"] == {}


def test_stage2_state_migrates_v2_payload_and_strips_entry_ids(tmp_path) -> None:
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

    assert payload["schema_version"] == 3
    instance = payload["meal_plan_instance_sync"]["1"]["instances"]["entry:1:primary:recipe:11"]
    assert "entry_ids" not in instance
