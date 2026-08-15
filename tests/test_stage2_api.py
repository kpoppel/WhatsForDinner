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


def test_stage2_shopping_view_and_sync(monkeypatch, tmp_path) -> None:
    use_temp_state(monkeypatch, tmp_path)

    class FakeClient:
        async def list_shopping_entries(self, limit=100):
            return {
                "results": [
                    {
                        "id": 1,
                        "food": {"name": "Milk", "category": "Dairy", "supermarket_category": "Cold"},
                        "amount": 1,
                        "checked": False,
                    },
                    {
                        "id": 2,
                        "food": {"name": "Apples", "category": "Fruit", "supermarket_category": "Produce"},
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
    sections = view_res.json()["data"]["sections"]
    assert len(sections["remaining"]) == 1
    assert len(sections["completed"]) == 1

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
