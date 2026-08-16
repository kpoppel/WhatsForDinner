from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services.stage2_state import Stage2State

client = TestClient(app)


def setup_module(module) -> None:
    from app import api as api_module

    api_module.settings.tandoor_write_enabled = True


def use_temp_state(monkeypatch, tmp_path):
    state_file = tmp_path / "stage2_state.json"
    state = Stage2State(str(state_file))
    monkeypatch.setattr("app.api.stage2_state", state)
    return state


def test_stage2_keyword_selection_roundtrip(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    put_res = client.put("/api/v1/config/keywords/selected", json={"keyword_ids": [4, 2, 2]})
    assert put_res.status_code == 200
    assert put_res.json()["selected_keyword_ids"] == [2, 4]

    get_res = client.get("/api/v1/config/keywords/selected")
    assert get_res.status_code == 200
    assert get_res.json()["selected_keyword_ids"] == [2, 4]


def test_stage2_meal_plan_rules_default_and_update(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    get_default = client.get("/api/v1/config/meal-plan-rules")
    assert get_default.status_code == 200
    assert get_default.json()["data"]["no_repeat_days"] == 30

    put_rules = client.put("/api/v1/config/meal-plan-rules", json={"no_repeat_days": 0})
    assert put_rules.status_code == 200
    assert put_rules.json()["data"]["no_repeat_days"] == 0

    get_updated = client.get("/api/v1/config/meal-plan-rules")
    assert get_updated.status_code == 200
    assert get_updated.json()["data"]["no_repeat_days"] == 0


def test_stage2_user_settings_roundtrip(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    get_default = client.get("/api/v1/config/user-settings")
    assert get_default.status_code == 200
    assert get_default.json()["data"]["default_diners"] == 2
    assert get_default.json()["data"]["default_notification_time"] == "08:00"

    put_res = client.put(
        "/api/v1/config/user-settings",
        json={"default_diners": 4, "default_notification_time": "07:30"},
    )
    assert put_res.status_code == 200
    assert put_res.json()["data"]["default_diners"] == 4
    assert put_res.json()["data"]["default_notification_time"] == "07:30"

    get_updated = client.get("/api/v1/config/user-settings")
    assert get_updated.status_code == 200
    assert get_updated.json()["data"]["default_diners"] == 4
    assert get_updated.json()["data"]["default_notification_time"] == "07:30"


def test_stage2_meal_plan_uses_all_recipes_when_no_keywords_selected(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            assert keyword_ids is None
            return {"results": [{"id": 9, "name": "Default Pantry Pick"}]}

    monkeypatch.setattr("app.api.client", FakeClient())

    res = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-17",
            "length_days": 1,
            "diners": 2,
        },
    )

    assert res.status_code == 200
    assert res.json()["data"]["entries"][0]["recipe"]["id"] == 9


def test_stage2_meal_plan_uses_default_diners_when_missing(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {"results": [{"id": 19, "name": "Default Diners Recipe"}]}

    monkeypatch.setattr("app.api.client", FakeClient())

    settings_res = client.put(
        "/api/v1/config/user-settings",
        json={"default_diners": 5, "default_notification_time": "08:15"},
    )
    assert settings_res.status_code == 200

    gen_res = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-17",
            "length_days": 1,
        },
    )
    assert gen_res.status_code == 200
    assert gen_res.json()["data"]["diners"] == 5
    assert gen_res.json()["data"]["entries"][0]["servings"] == 5


def test_stage2_meal_plan_generate_and_entry_ops(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {
                "results": [
                    {"id": 40, "name": "Tray Bake"},
                    {"id": 41, "name": "Tomato Pasta"},
                ]
            }

        async def get_recipe(self, recipe_id):
            return {
                "id": recipe_id,
                "steps": [
                    {
                        "ingredients": [
                            {"id": 1000 + int(recipe_id), "amount": 1, "food": {"name": "ingredient"}}
                        ]
                    }
                ],
            }

        async def update_recipe_shopping(self, recipe_id, payload):
            return {"updated_for": recipe_id, "payload": payload}

        async def list_shopping_entries(self, limit=100):
            return {
                "results": [
                    {
                        "id": 200,
                        "food": {"name": "Tomato", "category": "Vegetables"},
                        "amount": 3,
                        "checked": False,
                    }
                ]
            }

    monkeypatch.setattr("app.api.client", FakeClient())

    client.put("/api/v1/config/keywords/selected", json={"keyword_ids": [2]})

    gen_res = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-17",
            "length_days": 4,
            "diners": 3,
            "constraints": {
                "leftover_days": [3],
                "takeout_days": [4],
            },
        },
    )
    assert gen_res.status_code == 200
    plan = gen_res.json()["data"]
    assert plan["plan_id"] >= 1
    assert len(plan["entries"]) == 4

    plan_id = plan["plan_id"]
    entry_id = plan["entries"][0]["entry_id"]

    move_res = client.patch(
        f"/api/v1/meal-plans/{plan_id}/entries/{entry_id}",
        json={"target_day_index": 2},
    )
    assert move_res.status_code == 200

    shop_res = client.post(f"/api/v1/meal-plans/{plan_id}/shopping-list")
    assert shop_res.status_code == 200
    assert shop_res.json()["data"]["shopping_view"] is not None


def test_stage2_no_repeat_blocks_recent_recipe(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {"results": [{"id": 101, "name": "Repeat Candidate"}]}

    monkeypatch.setattr("app.api.client", FakeClient())
    client.put("/api/v1/config/keywords/selected", json={"keyword_ids": [5]})

    first = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-01",
            "length_days": 1,
            "diners": 2,
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["entries"][0]["recipe"]["id"] == 101

    second = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
        },
    )
    assert second.status_code == 200
    assert second.json()["data"]["no_repeat_days"] == 30
    assert second.json()["data"]["entries"][0]["recipe"] is None


def test_stage2_no_repeat_zero_allows_reuse(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {"results": [{"id": 202, "name": "Always Allowed"}]}

    monkeypatch.setattr("app.api.client", FakeClient())
    client.put("/api/v1/config/keywords/selected", json={"keyword_ids": [6]})
    client.put("/api/v1/config/meal-plan-rules", json={"no_repeat_days": 0})

    first = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-01",
            "length_days": 1,
            "diners": 2,
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["entries"][0]["recipe"]["id"] == 202

    second = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-02",
            "length_days": 1,
            "diners": 2,
        },
    )
    assert second.status_code == 200
    assert second.json()["data"]["no_repeat_days"] == 0
    assert second.json()["data"]["entries"][0]["recipe"]["id"] == 202


def test_stage2_stored_meal_plan_list_and_delete(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {"results": [{"id": 77, "name": "Rice Bowl"}]}

    monkeypatch.setattr("app.api.client", FakeClient())

    client.put("/api/v1/config/keywords/selected", json={"keyword_ids": [1]})

    gen_res = client.post(
        "/api/v1/meal-plans/generate",
        json={
            "start_date": "2026-08-18",
            "length_days": 3,
            "diners": 2,
        },
    )
    assert gen_res.status_code == 200
    plan_id = gen_res.json()["data"]["plan_id"]

    list_res = client.get("/api/v1/meal-plans/stored")
    assert list_res.status_code == 200
    assert list_res.json()["count"] == 1
    assert list_res.json()["data"][0]["plan_id"] == plan_id

    delete_res = client.delete(f"/api/v1/meal-plans/stored/{plan_id}")
    assert delete_res.status_code == 200
    assert delete_res.json()["data"]["deleted"] is True

    list_after_delete = client.get("/api/v1/meal-plans/stored")
    assert list_after_delete.status_code == 200
    assert list_after_delete.json()["count"] == 0


def test_stage2_stored_meal_plans_sorted_by_start_date_proximity(monkeypatch, tmp_path) -> None:
    state = use_temp_state(monkeypatch, tmp_path)

    today = date.today()
    start_today = today.isoformat()
    start_plus_two = (today + timedelta(days=2)).isoformat()
    start_plus_ten = (today + timedelta(days=10)).isoformat()

    state.create_meal_plan(
        {
            "start_date": start_plus_ten,
            "length_days": 3,
            "diners": 2,
            "keyword_ids": [],
            "entries": [],
        }
    )
    state.create_meal_plan(
        {
            "start_date": start_today,
            "length_days": 3,
            "diners": 2,
            "keyword_ids": [],
            "entries": [],
        }
    )
    state.create_meal_plan(
        {
            "start_date": start_plus_two,
            "length_days": 3,
            "diners": 2,
            "keyword_ids": [],
            "entries": [],
        }
    )

    list_res = client.get("/api/v1/meal-plans/stored")
    assert list_res.status_code == 200

    starts = [row["start_date"] for row in list_res.json()["data"]]
    assert starts == [start_today, start_plus_two, start_plus_ten]


def test_stage2_shopping_view_and_sync(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_shopping_entries(self, limit=100):
            return {
                "results": [
                    {
                        "id": 1,
                        "food": {
                            "name": "Milk",
                            "category": "Dairy",
                            "store_group": {"id": 6, "name": "Kød, fisk og fjerkræ"},
                        },
                        "amount": 1,
                        "checked": False,
                    },
                    {
                        "id": 2,
                        "food": {
                            "name": "Chicken",
                            "category": "Protein",
                            "store_group": {"id": 6, "name": "Kød, fisk og fjerkræ"},
                        },
                        "amount": 4,
                        "checked": False,
                    },
                    {
                        "id": 3,
                        "food": {
                            "name": "Apples",
                            "category": "Fruit",
                            "store_group": {"id": 9, "name": "Frugt og grøntsager"},
                        },
                        "amount": 4,
                        "checked": True,
                    },
                ]
            }

        async def update_shopping_entry(self, entry_id, payload):
            return {"id": entry_id, **payload}

        async def create_shopping_entry(self, payload):
            return {"id": 10, **payload}

        async def delete_shopping_entry(self, entry_id):
            return {"deleted": entry_id}

    monkeypatch.setattr("app.api.client", FakeClient())

    view_res = client.get("/api/v1/shopping-list/view")
    assert view_res.status_code == 200
    payload = view_res.json()["data"]
    sections = payload["sections"]
    assert len(sections["remaining"]) == 2
    assert len(sections["completed"]) == 1

    store_layout = payload["grouped"]["store_layout"]["remaining"]
    assert list(store_layout.keys()) == ["6"]
    assert store_layout["6"][0]["store_group"]["name"] == "Kød, fisk og fjerkræ"

    completed_store_layout = payload["grouped"]["store_layout"]["completed"]
    assert list(completed_store_layout.keys()) == ["9"]

    patch_res = client.patch("/api/v1/shopping-list/entries/1", json={"status": "skipped"})
    assert patch_res.status_code == 200
    assert patch_res.json()["effective_status"] == "skipped"
    skipped_payload = patch_res.json()["data"]
    assert skipped_payload["checked"] is False
    assert isinstance(skipped_payload.get("delay_until"), str)

    done_res = client.patch("/api/v1/shopping-list/entries/1", json={"status": "completed"})
    assert done_res.status_code == 200
    done_payload = done_res.json()["data"]
    assert done_payload["checked"] is True
    assert done_payload.get("delay_until") is None

    sync_res = client.get("/api/v1/shopping-list/sync?since=0")
    assert sync_res.status_code == 200
    assert sync_res.json()["server_cursor"] >= 1


def test_stage2_shopping_view_uses_supermarket_category_name(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_shopping_entries(self, limit=100):
            return {
                "results": [
                    {
                        "id": 10,
                        "food": {
                            "name": "Beef",
                            "category": "Protein",
                            "supermarket_category": {"id": 6, "name": "Kød, fisk og fjerkræ"},
                        },
                        "amount": 2,
                        "checked": False,
                    }
                ]
            }

        async def update_shopping_entry(self, entry_id, payload):
            return {"id": entry_id, **payload}

        async def create_shopping_entry(self, payload):
            return {"id": 99, **payload}

        async def delete_shopping_entry(self, entry_id):
            return {"deleted": entry_id}

    monkeypatch.setattr("app.api.client", FakeClient())

    response = client.get("/api/v1/shopping-list/view")
    assert response.status_code == 200
    item = response.json()["data"]["sections"]["remaining"][0]
    assert item["store_group"]["name"] == "Kød, fisk og fjerkræ"
    assert item["store_group"]["id"] == 6


def test_stage2_plan_shopping_uses_recipe_shopping_update(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    attempted_updates: list[dict] = []

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {"results": [{"id": 88, "name": "Fallback Recipe"}]}

        async def get_recipe(self, recipe_id):
            return {
                "id": recipe_id,
                "steps": [
                    {
                        "ingredients": [
                            {"id": 9088, "amount": 1, "food": {"name": "onion"}},
                            {"id": 9089, "amount": 2, "food": {"name": "garlic"}},
                        ]
                    }
                ],
            }

        async def update_recipe_shopping(self, recipe_id, payload):
            attempted_updates.append({"recipe_id": recipe_id, "payload": payload})
            return {"ok": True, "recipe_id": recipe_id, "payload": payload}

        async def list_shopping_entries(self, limit=100):
            return {"results": []}

    monkeypatch.setattr("app.api.client", FakeClient())
    client.put("/api/v1/config/keywords/selected", json={"keyword_ids": [3]})

    plan_res = client.post(
        "/api/v1/meal-plans/generate",
        json={"start_date": "2026-08-20", "length_days": 1, "diners": 2},
    )
    assert plan_res.status_code == 200
    plan_id = plan_res.json()["data"]["plan_id"]

    shopping_res = client.post(f"/api/v1/meal-plans/{plan_id}/shopping-list")
    assert shopping_res.status_code == 200
    assert shopping_res.json()["data"]["failed"] == []
    assert len(shopping_res.json()["data"]["created"]) == 1
    assert len(attempted_updates) == 1
    assert attempted_updates[0]["recipe_id"] == 88
    assert attempted_updates[0]["payload"]["servings"] == 2
    assert attempted_updates[0]["payload"]["ingredients"] == [9088, 9089]


def test_stage2_write_route_blocked_when_read_only(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)
    from app import api as api_module

    api_module.settings.tandoor_write_enabled = False

    try:
        response = client.post(
            "/api/v1/shopping-list/entries",
            json={"food": {"name": "Milk"}, "amount": 1},
        )
        assert response.status_code == 409
        assert "disabled" in response.json()["detail"].lower()
    finally:
        api_module.settings.tandoor_write_enabled = True


def test_stage2_ad_hoc_entries_persist_locally_and_merge(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_shopping_entries(self, limit=100):
            return {
                "results": [
                    {
                        "id": 100,
                        "food": {"name": "Milk", "category": "Dairy"},
                        "amount": 1,
                        "checked": False,
                    }
                ]
            }

        async def update_shopping_entry(self, entry_id, payload):
            return {"id": entry_id, **payload}

        async def create_shopping_entry(self, payload):
            return {"id": 200, **payload}

        async def delete_shopping_entry(self, entry_id):
            return {"deleted": entry_id}

    monkeypatch.setattr("app.api.client", FakeClient())

    create_res = client.post(
        "/api/v1/shopping-list/entries",
        json={
            "ad_hoc": True,
            "name": "Ice",
            "amount": 2,
            "ingredient_type": "Frozen",
            "store_group": {"name": "General"},
            "status": "remaining",
            "reminder_enabled": True,
            "reminder_date": "2026-08-21",
            "reminder_text": "Move tray to freezer",
        },
    )
    assert create_res.status_code == 200
    created = create_res.json()["data"]
    local_id = created["id"]
    assert isinstance(local_id, int)
    assert local_id < 0
    assert created["source"] == "local"

    view_res = client.get("/api/v1/shopping-list/view")
    assert view_res.status_code == 200
    remaining = view_res.json()["data"]["sections"]["remaining"]
    names = {row["name"] for row in remaining}
    assert "Milk" in names
    assert "Ice" in names

    local_row = next(row for row in remaining if row["id"] == local_id)
    assert local_row["reminder_enabled"] is True
    assert local_row["reminder_text"] == "Move tray to freezer"

    patch_res = client.patch(
        f"/api/v1/shopping-list/entries/{local_id}",
        json={"amount": 2.5, "status": "completed", "reminder_enabled": False, "reminder_date": None},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["data"]["amount"] == 2.5
    assert patch_res.json()["effective_status"] == "completed"

    delete_res = client.delete(f"/api/v1/shopping-list/entries/{local_id}")
    assert delete_res.status_code == 200

    after_delete = client.get("/api/v1/shopping-list/view")
    assert after_delete.status_code == 200
    remaining_after = after_delete.json()["data"]["sections"]["remaining"]
    completed_after = after_delete.json()["data"]["sections"]["completed"]
    ids_after = {row["id"] for row in remaining_after + completed_after}
    assert local_id not in ids_after


def test_stage2_ad_hoc_create_allowed_when_tandoor_writes_disabled(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)
    from app import api as api_module

    class FakeClient:
        async def list_shopping_entries(self, limit=100):
            return {"results": []}

    monkeypatch.setattr("app.api.client", FakeClient())
    api_module.settings.tandoor_write_enabled = False
    try:
        response = client.post(
            "/api/v1/shopping-list/entries",
            json={"ad_hoc": True, "name": "Paper Towels", "amount": 1},
        )
        assert response.status_code == 200
        assert response.json()["source"] == "local-state"
    finally:
        api_module.settings.tandoor_write_enabled = True
