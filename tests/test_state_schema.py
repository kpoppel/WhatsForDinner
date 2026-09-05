import json
from datetime import date, timedelta

import pytest

from app.services.server_state import ServerState
from app.services.state_migrations import StateSchemaError


def test_stage2_state_writes_schema_version(tmp_path) -> None:
    state = ServerState(str(tmp_path))

    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    assert payload["schema_version"] == 18
    assert "archive" not in payload
    assert "shopping_sync_events" not in payload


def test_stage2_state_flush_persists_memory_changes(tmp_path) -> None:
    state = ServerState(str(tmp_path))

    state.set_selected_keywords([4])
    state.flush()

    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    assert payload["selected_keyword_ids"] == [4]


def test_recipe_use_history_is_append_only_across_plan_changes(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    plan = state.create_meal_plan(
        {
            "entries": [
                {
                    "entry_id": 1,
                    "date": "2026-09-01",
                    "recipes": [
                        {"id": 11, "title": "Roast Veg", "purpose": "meal"},
                        {"id": 12, "title": "Rice Bowl", "purpose": "meal"},
                    ],
                }
            ]
        }
    )

    state.update_meal_plan(plan["plan_id"], {"diners": 4})
    state.update_meal_plan(
        plan["plan_id"],
        {
            "entries": [
                {
                    "entry_id": 1,
                    "date": "2026-09-02",
                    "recipes": [{"id": 13, "title": "Pasta", "purpose": "meal"}],
                }
            ]
        },
    )
    state.delete_meal_plan(plan["plan_id"])
    state.flush()

    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    assert payload["recipe_use_history"] == [
        {"recipe_id": 11, "used_date": "2026-09-01", "plan_id": 1, "entry_id": 1},
        {"recipe_id": 12, "used_date": "2026-09-01", "plan_id": 1, "entry_id": 1},
        {"recipe_id": 13, "used_date": "2026-09-02", "plan_id": 1, "entry_id": 1},
    ]


def test_recipe_use_history_backfills_existing_plans_on_startup(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    state.create_meal_plan(
        {
            "entries": [
                {
                    "entry_id": 1,
                    "date": "2026-09-01",
                        "recipe": {"id": 11, "title": "Roast Veg"},
                }
            ]
        }
    )
    state.flush()

    payload = json.loads(state.state_file.read_text(encoding="utf-8"))
    payload["schema_version"] = 10
    payload["recipe_use_history"] = []
    state.state_file.write_text(json.dumps(payload), encoding="utf-8")

    restored = ServerState(str(tmp_path))
    restored.flush()

    with restored.state_file.open("r", encoding="utf-8") as fp:
        restored_payload = json.load(fp)
    assert restored_payload["recipe_use_history"] == [
        {"recipe_id": 11, "used_date": "2026-09-01", "plan_id": 1, "entry_id": 1}
    ]


def test_recipe_use_history_prunes_to_the_configured_window(tmp_path) -> None:
    state = ServerState(str(tmp_path))
    today = date.today()
    plan = state.create_meal_plan(
        {
            "entries": [
                {
                    "entry_id": 1,
                    "date": (today - timedelta(days=31)).isoformat(),
                    "recipes": [{"id": 11, "title": "Old Recipe", "purpose": "meal"}],
                },
                {
                    "entry_id": 2,
                    "date": (today - timedelta(days=30)).isoformat(),
                    "recipes": [{"id": 12, "title": "Recent Recipe", "purpose": "meal"}],
                },
            ]
        }
    )

    state.set_meal_plan_rules(30)
    state.flush()

    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    assert payload["recipe_use_history"] == [
        {
            "recipe_id": 12,
            "used_date": (today - timedelta(days=30)).isoformat(),
            "plan_id": plan["plan_id"],
            "entry_id": 2,
        }
    ]

    state.set_meal_plan_rules(0)
    state.flush()
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    assert payload["recipe_use_history"] == []


def test_stage2_state_persists_compact_pending_shopping_changes(tmp_path) -> None:
    state = ServerState(str(tmp_path))

    state.set_pending_shopping_changes(
        [
            {"operation": "update", "entry_id": 4, "payload": {"status": "completed"}},
            {"operation": "delete", "entry_id": 9, "payload": {}},
        ]
    )
    state.flush()

    restored = ServerState(str(tmp_path))
    assert restored.pending_shopping_changes() == {
        "4": {"operation": "update", "entry_id": 4, "payload": {"status": "completed"}},
        "9": {"operation": "delete", "entry_id": 9, "payload": {}},
    }


def test_stage2_state_invalid_payload_fails_fast(tmp_path) -> None:
    invalid_payload = {
        "schema_version": 4,
        "selected_keyword_ids": [],
        "meal_plan_rules": {"no_repeat_days": "bad"},
        "user_settings": {
            "default_diners": 2,
            "default_notification_time": "08:00",
        },
        "meal_plans": {"1": {"plan_id": 1}},
        "next_meal_plan_id": 1,
        "next_entry_id": 1,
        "shopping_status_overrides": {},
        "shopping_item_metadata": {},
        "local_shopping_entries": {},
        "next_local_shopping_entry_id": -1,
        "tandoor_sync": {},
        "shopping_sync_events": [],
        "next_sync_event_id": 1,
        "archive": {"meal_plans": [], "sync_events": []},
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(invalid_payload), encoding="utf-8")

    with pytest.raises(StateSchemaError):
        ServerState(str(tmp_path))


def test_stage2_state_migrates_v1_payload_to_v8(tmp_path) -> None:
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
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(legacy_payload), encoding="utf-8")
    state = ServerState(str(tmp_path))

    assert state.selected_keywords() == []
    state.set_selected_keywords([])
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    assert payload["schema_version"] == 18
    assert "meal_plan_instance_sync" not in payload
    assert "archive" not in payload


def test_stage2_state_migrates_v2_payload_and_strips_entry_ids(tmp_path) -> None:
    v2_payload = {
        "schema_version": 2,
        "selected_keyword_ids": [],
        "meal_plan_rules": {"no_repeat_days": 30},
        "user_settings": {
            "default_diners": 2,
            "default_notification_time": "08:00",
        },
        "meal_plans": {
            "1": {
                "plan_id": 1,
                "entries": [
                    {
                        "entry_id": 1,
                        "recipe": {"id": 11, "title": "Roast Veg"},
                        "extra_recipes": [],
                    }
                ],
            }
        },
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
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(v2_payload), encoding="utf-8")
    state = ServerState(str(tmp_path))

    assert state.selected_keywords() == []
    state.set_selected_keywords([])
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    assert payload["schema_version"] == 18
    recipe = payload["meal_plans"]["1"]["entries"][0]["recipes"][0]
    assert recipe["tandoor_sync"] == {"meal_plan_row_id": 5, "shopping_recipe_id": 7}
    assert "tandoor_sync" not in payload["meal_plans"]["1"]


def test_stage2_state_migrates_v3_payload_to_v8_without_event_history(tmp_path) -> None:
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
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(v3_payload), encoding="utf-8")
    state = ServerState(str(tmp_path))

    assert state.selected_keywords() == []
    state.set_selected_keywords([])
    with state.state_file.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    assert payload["schema_version"] == 18
    assert "archive" not in payload
    assert "shopping_sync_events" not in payload
    assert "next_sync_event_id" not in payload


def test_stage2_state_migrates_v8_payload_without_shopping_snapshot(tmp_path) -> None:
    payload = {
        "schema_version": 8,
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
        "recipe_use_history": [],
        "shopping_snapshot": [{"id": 1, "name": "Large remote entry"}],
        "pending_shopping_changes": {},
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(payload), encoding="utf-8")

    ServerState(str(tmp_path))

    with state_file.open("r", encoding="utf-8") as fp:
        migrated_payload = json.load(fp)
    assert migrated_payload["schema_version"] == 18
    assert "shopping_snapshot" not in migrated_payload


def test_stage2_state_migrates_v9_payload_without_remote_status_overrides(tmp_path) -> None:
    payload = {
        "schema_version": 9,
        "selected_keyword_ids": [],
        "meal_plan_rules": {"no_repeat_days": 30},
        "user_settings": {
            "default_diners": 2,
            "default_notification_time": "08:00",
        },
        "meal_plans": {},
        "next_meal_plan_id": 1,
        "next_entry_id": 1,
        "shopping_status_overrides": {"1949": "completed", "-1": "skipped"},
        "shopping_item_metadata": {},
        "local_shopping_entries": {},
        "next_local_shopping_entry_id": -1,
        "meal_plan_instance_sync": {},
        "recipe_use_history": [],
        "pending_shopping_changes": {},
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(payload), encoding="utf-8")

    state = ServerState(str(tmp_path))

    assert state.get_shopping_statuses() == {"-1": "skipped"}
