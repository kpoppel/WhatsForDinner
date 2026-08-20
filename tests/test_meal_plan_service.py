import asyncio
from datetime import date

import pytest
from fastapi import HTTPException

from app.services.meal_plan_service import MealPlanService
from app.services.stage2_state import Stage2State
from app.services.tandoor_client import TandoorError


class FakeMealClient:
    def __init__(self) -> None:
        self.updated_shopping_calls = []
        self.deleted_shopping_calls = []
        self.meal_plan_rows: dict[int, dict] = {}
        self.next_meal_plan_row_id = 1
        self.next_entry_id = 2
        self.shopping_entries = [
            {
                "id": 1,
                "food": {"name": "Carrot", "category": "Vegetables"},
                "amount": 2,
                "checked": False,
            }
        ]

    async def list_recipes(self, search=None, limit=20, keyword_ids=None):
        return {
            "results": [
                {"id": 11, "name": "Roast Veg"},
                {"id": 12, "name": "Rice Bowl"},
            ]
        }

    async def get_recipe(self, recipe_id):
        return {
            "id": recipe_id,
            "steps": [{"ingredients": [{"id": 100 + recipe_id}]}],
            "ingredients": [],
        }

    async def update_recipe_shopping(self, recipe_id, payload):
        self.updated_shopping_calls.append((recipe_id, payload))
        ingredients = payload.get("ingredients")
        servings = payload.get("servings")
        if isinstance(ingredients, list):
            for ingredient_id in ingredients:
                if not isinstance(ingredient_id, int):
                    continue
                self.shopping_entries.append(
                    {
                        "id": self.next_entry_id,
                        "food": {"name": f"Ingredient {ingredient_id}", "category": "Other"},
                        "amount": servings,
                        "checked": False,
                        "ingredient": ingredient_id,
                        "list_recipe_data": {
                            "recipe_data": {
                                "id": recipe_id,
                                "name": f"Recipe {recipe_id}",
                            }
                        },
                    }
                )
                self.next_entry_id += 1
        return {"ok": True, "recipe_id": recipe_id, "payload": payload}

    async def delete_shopping_entry(self, entry_id):
        self.deleted_shopping_calls.append(entry_id)
        self.shopping_entries = [row for row in self.shopping_entries if int(row.get("id", -1)) != entry_id]
        return {"deleted": entry_id}

    async def list_shopping_entries(self, limit=100):
        return {"results": self.shopping_entries[:limit]}

    async def list_meal_plans(self, limit=50):
        rows = list(self.meal_plan_rows.values())
        rows.sort(key=lambda row: int(row.get("id", 0)))
        return {"results": rows[:limit]}

    async def create_meal_plan(self, payload):
        row_id = self.next_meal_plan_row_id
        self.next_meal_plan_row_id += 1
        row = {"id": row_id, **payload}
        self.meal_plan_rows[row_id] = row
        return row

    async def delete_meal_plan(self, meal_id):
        self.meal_plan_rows.pop(int(meal_id), None)
        return {"deleted": int(meal_id)}

    async def list_meal_types(self, limit=50):
        return {
            "results": [
                {
                    "id": 5,
                    "name": "Aftensmad",
                    "order": 0,
                    "time": "18:00:00",
                    "color": "#1F5ECD",
                }
            ]
        }


class BrokenMealClient(FakeMealClient):
    async def list_recipes(self, search=None, limit=20, keyword_ids=None):
        raise TandoorError("recipes unavailable")


class MissingDeleteMealClient(FakeMealClient):
    async def delete_shopping_entry(self, entry_id):
        self.deleted_shopping_calls.append(entry_id)
        raise TandoorError(f"Tandoor returned 404 for /api/shopping-list-entry/{entry_id}/.")


def ensure_writes_enabled(_operation: str) -> None:
    return


def build_shopping_view(entries: list[dict]) -> dict:
    return {"count": len(entries)}


def test_generate_plan_reuses_constraints_and_entries(tmp_path, monkeypatch) -> None:
    state = Stage2State(str(tmp_path))
    service = MealPlanService(state, FakeMealClient())

    # Existing plan history should prevent immediate repeat when no_repeat_days is active.
    state.create_meal_plan(
        {
            "start_date": "2026-08-01",
            "length_days": 1,
            "diners": 2,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-01",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Roast Veg"},
                    "servings": 2,
                    "reminder_enabled": False,
                    "reminder_text": "",
                    "notes": "",
                }
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    monkeypatch.setattr("app.services.meal_plan_service.random.SystemRandom.shuffle", lambda _self, values: None)

    result = asyncio.run(
        service.generate_plan(
            start_day=date(2026, 8, 10),
            length_days=3,
            diners=4,
            constraints={"leftover_days": [2], "takeout_days": [3], "empty_days": []},
            keyword_ids=[7],
            no_repeat_days=30,
        )
    )

    entries = result["data"]["entries"]
    assert len(entries) == 3
    assert entries[0]["recipe"]["id"] == 12
    assert entries[1]["mode"] == "leftover"
    assert entries[1]["recipe"]["id"] == 12
    assert entries[2]["mode"] == "takeout"


def test_patch_plan_rebases_dates_and_length(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    service = MealPlanService(state, FakeMealClient())

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 2,
            "diners": 2,
            "entries": [
                {"entry_id": 1, "day_index": 0, "date": "2026-08-10", "mode": "planned", "recipe": None},
                {"entry_id": 2, "day_index": 1, "date": "2026-08-11", "mode": "planned", "recipe": None},
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    patched = asyncio.run(service.patch_plan(plan["plan_id"], {"start_date": "2026-08-20"}))

    assert patched["data"]["start_date"] == "2026-08-20"
    assert [row["day_index"] for row in patched["data"]["entries"]] == [0, 1]
    assert [row["date"] for row in patched["data"]["entries"]] == ["2026-08-20", "2026-08-21"]


def test_generate_shopping_from_plan_aggregates_success_and_failure(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 2,
            "diners": 3,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Roast Veg"},
                    "servings": 3,
                },
                {
                    "entry_id": 2,
                    "day_index": 1,
                    "date": "2026-08-11",
                    "mode": "planned",
                    "recipe": {"id": 12, "title": "Rice Bowl"},
                    "servings": 3,
                },
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    async def failing_update(recipe_id, payload):
        if recipe_id == 12:
            raise TandoorError("cannot update shopping")
        return {"ok": True, "recipe_id": recipe_id, "payload": payload}

    client.update_recipe_shopping = failing_update

    result = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )

    data = result["data"]
    assert len(data["created"]) >= 1
    assert len(data["failed"]) == 1
    created_recipe_updates = [row for row in data["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(created_recipe_updates) == 1
    assert created_recipe_updates[0]["recipe_id"] == 11
    assert data["failed"][0]["recipe_id"] == 12
    assert data["shopping_view"]["count"] == 1


def test_generate_shopping_from_plan_includes_all_extra_recipes(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 3,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Roast Veg"},
                    "extra_recipes": [
                        {"purpose": "meal", "recipe": {"id": 12, "title": "Rice Bowl"}},
                        {"purpose": "shopping_only", "recipe": {"id": 13, "title": "Pantry"}},
                    ],
                    "servings": 3,
                }
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    result = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )

    data = result["data"]
    created_recipe_updates = [row for row in data["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(created_recipe_updates) == 3
    assert len(data["failed"]) == 0
    recipe_ids = sorted([row["recipe_id"] for row in created_recipe_updates])
    assert recipe_ids == [11, 12, 13]


def test_generate_shopping_from_plan_is_idempotent_and_syncs_add_remove(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Roast Veg"},
                    "extra_recipes": [],
                    "servings": 2,
                }
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    first = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    first_recipe_updates = [row for row in first["data"]["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(first_recipe_updates) == 1
    assert first_recipe_updates[0]["recipe_id"] == 11

    client.updated_shopping_calls.clear()
    second = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    assert len(second["data"]["created"]) == 0
    assert len(second["data"]["failed"]) == 0
    assert client.updated_shopping_calls == []

    updated_plan = state.get_meal_plan(plan["plan_id"])
    assert isinstance(updated_plan, dict)
    entries = updated_plan.get("entries") if isinstance(updated_plan.get("entries"), list) else []
    entries[0]["extra_recipes"] = [
        {"purpose": "shopping_only", "recipe": {"id": 13, "title": "Pantry"}}
    ]
    state.update_meal_plan(plan["plan_id"], {"entries": entries})

    client.updated_shopping_calls.clear()
    third = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    third_recipe_updates = [row for row in third["data"]["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(third_recipe_updates) == 1
    assert third_recipe_updates[0]["recipe_id"] == 13

    updated_plan = state.get_meal_plan(plan["plan_id"])
    assert isinstance(updated_plan, dict)
    entries = updated_plan.get("entries") if isinstance(updated_plan.get("entries"), list) else []
    entries[0]["extra_recipes"] = []
    state.update_meal_plan(plan["plan_id"], {"entries": entries})

    client.updated_shopping_calls.clear()
    fourth = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    removal_rows = [
        row
        for row in fourth["data"]["created"]
        if row.get("operation") == "shopping_entry_delete" and row.get("recipe_id") == 13
    ]
    assert len(removal_rows) >= 1
    assert removal_rows[0]["recipe_source"] == "sync_remove"


def test_generate_shopping_from_plan_same_recipe_on_second_day_increases_servings(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Roast Veg"},
                    "extra_recipes": [],
                    "servings": 2,
                }
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    first = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    first_recipe_updates = [row for row in first["data"]["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(first_recipe_updates) == 1

    updated_plan = state.get_meal_plan(plan["plan_id"])
    assert isinstance(updated_plan, dict)
    entries = updated_plan.get("entries") if isinstance(updated_plan.get("entries"), list) else []
    entries.append(
        {
            "entry_id": 2,
            "day_index": 1,
            "date": "2026-08-11",
            "mode": "planned",
            "recipe": {"id": 11, "title": "Roast Veg"},
            "extra_recipes": [],
            "servings": 2,
        }
    )
    state.update_meal_plan(plan["plan_id"], {"entries": entries, "length_days": 2})

    client.updated_shopping_calls.clear()
    second = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )

    assert len(client.updated_shopping_calls) == 1
    recipe_id, payload = client.updated_shopping_calls[0]
    assert recipe_id == 11
    assert payload["servings"] == 2
    assert len(second["data"]["created"]) >= 1


def test_generate_plan_wraps_tandoor_list_errors(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    service = MealPlanService(state, BrokenMealClient())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.generate_plan(
                start_day=date(2026, 8, 10),
                length_days=2,
                diners=2,
                constraints={"leftover_days": [], "takeout_days": [], "empty_days": []},
                keyword_ids=[],
                no_repeat_days=0,
            )
        )

    assert exc_info.value.status_code == 502


def test_generate_shopping_remove_then_readd_same_recipe_resyncs_when_tracked_entry_missing(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = MissingDeleteMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Roast Veg"},
                    "extra_recipes": [],
                    "servings": 2,
                }
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    first = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    first_recipe_updates = [row for row in first["data"]["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(first_recipe_updates) == 1

    # Simulate list entries being removed outside our tracked state before the recipe is removed from the plan.
    client.shopping_entries = [
        {
            "id": 1,
            "food": {"name": "Carrot", "category": "Vegetables"},
            "amount": 2,
            "checked": False,
        }
    ]

    state.update_meal_plan(
        plan["plan_id"],
        {
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                }
            ]
        },
    )

    removed = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    assert len(removed["data"]["failed"]) == 0

    state.update_meal_plan(
        plan["plan_id"],
        {
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Roast Veg"},
                    "extra_recipes": [],
                    "servings": 2,
                }
            ]
        },
    )

    readded = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    readd_recipe_updates = [row for row in readded["data"]["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(readd_recipe_updates) == 1

    client.updated_shopping_calls.clear()
    readded = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )

    assert len(client.updated_shopping_calls) == 0
    readded_recipe_updates = [row for row in readded["data"]["created"] if row.get("operation") == "recipe_shopping_update"]
    assert readded_recipe_updates == []
