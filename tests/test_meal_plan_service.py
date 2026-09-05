"""Meal-plan generation, projection, retry, and shopping orchestration tests."""

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
        self.shopping_recipe_rows: dict[int, dict] = {}
        self.next_shopping_recipe_id = 1
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
        ingredient_id = 100 + recipe_id
        return {
            "id": recipe_id,
            "steps": [
                {
                    "ingredients": [
                        {
                            "id": ingredient_id,
                            "amount": 1,
                            "unit": {"id": 1, "name": "g"},
                            "food": {
                                "id": ingredient_id,
                                "name": f"Ingredient {ingredient_id}",
                                "ignore_shopping": False,
                            },
                        }
                    ]
                }
            ],
            "ingredients": [],
        }

    async def create_shopping_list_from_recipe(self, payload):
        row_id = self.next_shopping_recipe_id
        self.next_shopping_recipe_id += 1
        row = {"id": row_id, **payload}
        self.shopping_recipe_rows[row_id] = row
        return row

    async def bulk_create_shopping_list_recipe_entries(self, shopping_recipe_id, payload):
        row = self.shopping_recipe_rows.get(shopping_recipe_id)
        if not isinstance(row, dict):
            raise TandoorError("shopping-list-recipe missing")

        recipe_id = row.get("recipe")
        servings = row.get("servings")
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            for item in entries:
                if not isinstance(item, dict):
                    continue
                food_id = item.get("food_id")
                ingredient_id = item.get("ingredient_id")
                amount = item.get("amount")
                if not isinstance(food_id, int) or not isinstance(ingredient_id, int):
                    continue
                self.shopping_entries.append(
                    {
                        "id": self.next_entry_id,
                        "food": {
                            "id": food_id,
                            "name": f"Ingredient {food_id}",
                            "category": "Other",
                        },
                        "amount": amount,
                        "checked": False,
                        "ingredient": ingredient_id,
                        "list_recipe_data": {
                            "recipe_data": {
                                "id": recipe_id,
                                "name": f"Recipe {recipe_id}",
                            }
                        },
                        "shopping_recipe_id": shopping_recipe_id,
                    }
                )
                self.next_entry_id += 1

        self.updated_shopping_calls.append(
            (
                recipe_id,
                {
                    "servings": servings,
                    "shopping_recipe_id": shopping_recipe_id,
                },
            )
        )
        return payload

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

    async def update_meal_plan(self, meal_id, payload):
        row_id = int(meal_id)
        row = self.meal_plan_rows.get(row_id)
        if not isinstance(row, dict):
            raise TandoorError(f"Tandoor returned 404 for /api/meal-plan/{row_id}/.")
        row.update(payload)
        return row

    async def delete_meal_plan(self, meal_id):
        mealplan_id = int(meal_id)
        self.meal_plan_rows.pop(mealplan_id, None)

        removed_shopping_recipe_ids: set[int] = set()
        for shopping_recipe_id, row in list(self.shopping_recipe_rows.items()):
            if int(row.get("mealplan", -1)) != mealplan_id:
                continue
            removed_shopping_recipe_ids.add(shopping_recipe_id)
            self.shopping_recipe_rows.pop(shopping_recipe_id, None)

        self.shopping_entries = [
            row
            for row in self.shopping_entries
            if not (
                isinstance(row, dict)
                and isinstance(row.get("shopping_recipe_id"), int)
                and row.get("shopping_recipe_id") in removed_shopping_recipe_ids
            )
        ]
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


class ProjectionFailureMealClient(FakeMealClient):
    async def list_recipes(self, search=None, limit=20, keyword_ids=None):
        return {"results": [{"id": 11, "name": "Roast Veg"}]}

    async def create_meal_plan(self, payload):
        raise TandoorError("Tandoor projection unavailable")


class AmbiguousCreateMealClient(FakeMealClient):
    def __init__(self) -> None:
        super().__init__()
        self.drop_create_response = True

    async def create_meal_plan(self, payload):
        created = await super().create_meal_plan(payload)
        if self.drop_create_response:
            self.drop_create_response = False
            raise TandoorError("Tandoor response was lost")
        return created


class AmbiguousUpdateMealClient(FakeMealClient):
    def __init__(self) -> None:
        super().__init__()
        self.create_calls = 0
        self.drop_response_on_call: int | None = None

    async def create_meal_plan(self, payload):
        self.create_calls += 1
        created = await super().create_meal_plan(payload)
        if self.create_calls == self.drop_response_on_call:
            raise TandoorError("Tandoor replacement response was lost")
        return created


class MissingDeleteMealClient(FakeMealClient):
    async def delete_shopping_entry(self, entry_id):
        self.deleted_shopping_calls.append(entry_id)
        raise TandoorError(f"Tandoor returned 404 for /api/shopping-list-entry/{entry_id}/.")


class OrderedDeleteMealClient(FakeMealClient):
    def __init__(self, *, fail_shopping_ids=None, missing_shopping_ids=None) -> None:
        super().__init__()
        self.fail_shopping_ids = set(fail_shopping_ids or [])
        self.missing_shopping_ids = set(missing_shopping_ids or [])
        self.call_order: list[str] = []

    async def delete_shopping_entry(self, entry_id):
        self.call_order.append(f"shopping:{entry_id}")
        if entry_id in self.fail_shopping_ids:
            raise TandoorError(f"Tandoor returned 500 for /api/shopping-list-entry/{entry_id}/.")
        if entry_id in self.missing_shopping_ids:
            raise TandoorError(f"Tandoor returned 404 for /api/shopping-list-entry/{entry_id}/.")
        return await super().delete_shopping_entry(entry_id)

    async def delete_meal_plan(self, meal_id):
        self.call_order.append(f"meal:{meal_id}")
        return await super().delete_meal_plan(meal_id)


class SparseRemoteMealPlanClient(FakeMealClient):
    def __init__(self) -> None:
        super().__init__()
        self.create_calls = 0
        self.delete_calls = 0

    async def list_meal_plans(self, limit=50):
        # Simulate a remote snapshot that omits existing ids.
        return {"results": []}

    async def create_meal_plan(self, payload):
        self.create_calls += 1
        return await super().create_meal_plan(payload)

    async def delete_meal_plan(self, meal_id):
        self.delete_calls += 1
        return await super().delete_meal_plan(meal_id)


def ensure_writes_enabled(_operation: str) -> None:
    return


def build_shopping_view(entries: list[dict]) -> dict:
    return {"count": len(entries)}


def test_generate_plan_reuses_constraints_and_entries(tmp_path, monkeypatch) -> None:
    state = Stage2State(str(tmp_path))
    service = MealPlanService(state, FakeMealClient())

    # Existing plan history should prevent immediate repeat when no_repeat_days is active.
    existing_plan = state.create_meal_plan(
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
    state.record_meal_plan_recipe_uses(int(existing_plan["plan_id"]))

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

    original_create_shopping = client.create_shopping_list_from_recipe

    async def failing_create_shopping(payload):
        recipe_id = payload.get("recipe") if isinstance(payload, dict) else None
        if recipe_id == 12:
            raise TandoorError("cannot update shopping")
        return await original_create_shopping(payload)

    client.create_shopping_list_from_recipe = failing_create_shopping

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
    assert data["shopping_view"]["count"] == 2


def test_generate_shopping_from_plan_includes_all_extra_recipes(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "plan_token": "a" * 32,
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

    first_generated_entry = next(
        row for row in client.shopping_entries if row.get("shopping_recipe_id") == 1
    )
    regenerated = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan["plan_id"],
            mode="regenerate_missing",
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    assert len(regenerated["data"]["created"]) == 1
    assert int(first_generated_entry["id"]) in client.deleted_shopping_calls
    assert client.shopping_entries[0]["id"] == 1
    regenerated_entries = [
        row for row in client.shopping_entries if row.get("shopping_recipe_id") == 2
    ]
    assert len(regenerated_entries) == 1

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
    assert fourth["data"]["failed"] == []
    recipe_13_entries = [
        row
        for row in client.shopping_entries
        if isinstance(row.get("list_recipe_data"), dict)
        and isinstance(row["list_recipe_data"].get("recipe_data"), dict)
        and row["list_recipe_data"]["recipe_data"].get("id") == 13
    ]
    assert len(recipe_13_entries) == 1


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


def test_generate_plan_discards_local_state_when_projection_fails(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    service = MealPlanService(state, ProjectionFailureMealClient())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.generate_plan(
                start_day=date(2026, 8, 10),
                length_days=1,
                diners=2,
                constraints={"leftover_days": [], "takeout_days": [], "empty_days": []},
                keyword_ids=[],
                no_repeat_days=0,
                ensure_tandoor_writes_enabled=ensure_writes_enabled,
            )
        )

    assert exc_info.value.status_code == 502
    assert state.list_meal_plans() == []
    assert state.pending_projections() == []


def test_ambiguous_create_does_not_leave_a_local_plan_projection(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = AmbiguousCreateMealClient()
    service = MealPlanService(state, client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.generate_plan(
                start_day=date(2026, 8, 10),
                length_days=1,
                diners=2,
                constraints={"leftover_days": [], "takeout_days": [], "empty_days": []},
                keyword_ids=[],
                no_repeat_days=0,
                ensure_tandoor_writes_enabled=ensure_writes_enabled,
            )
        )

    assert exc_info.value.status_code == 502
    assert len(client.meal_plan_rows) == 1
    assert state.list_meal_plans() == []
    assert state.pending_projections() == []


def test_pending_projection_reconciliation_adopts_ambiguous_remote_replacement(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = AmbiguousUpdateMealClient()
    service = MealPlanService(state, client)

    generated = asyncio.run(
        service.generate_plan(
            start_day=date(2026, 8, 10),
            length_days=2,
            diners=2,
            constraints={"leftover_days": [], "takeout_days": [], "empty_days": []},
            keyword_ids=[],
            no_repeat_days=0,
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
        )
    )
    plan_id = generated["data"]["plan_id"]
    assert len(client.meal_plan_rows) == 2

    patched = asyncio.run(
        service.patch_plan(
            plan_id,
            {"start_date": "2026-08-20"},
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
        )
    )
    assert patched["projection"]["status"] == "synchronized"
    assert len(client.meal_plan_rows) == 2

    instance_notes = [row["note"] for row in client.meal_plan_rows.values()]
    assert len(instance_notes) == 2
    assert len(set(instance_notes)) == 2
    assert state.pending_projections() == []


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


def test_sync_tandoor_meal_plan_includes_mode_only_rows_without_recipe(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 3,
            "diners": 2,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "leftover",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                },
                {
                    "entry_id": 2,
                    "day_index": 1,
                    "date": "2026-08-11",
                    "mode": "takeout",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                },
                {
                    "entry_id": 3,
                    "day_index": 2,
                    "date": "2026-08-12",
                    "mode": "empty",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                },
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    asyncio.run(service._sync_tandoor_meal_plan_rows(
        plan_id=plan["plan_id"],
        plan_payload=plan,
        ensure_tandoor_writes_enabled=ensure_writes_enabled,
        operation_name="test_seed",
    ))

    rows = list(client.meal_plan_rows.values())
    assert len(rows) == 3
    titles = [str(row.get("title") or "") for row in rows]
    assert set(titles) == {"Leftovers", "Takeout", "Eating Out"}
    assert all("recipe" not in row for row in rows)


def test_patch_entry_switch_to_non_planned_clears_recipe_and_syncs_mode_row(tmp_path) -> None:
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
                    "extra_recipes": [{"purpose": "meal", "recipe": {"id": 12, "title": "Rice Bowl"}}],
                    "servings": 2,
                }
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )

    updated = asyncio.run(
        service.patch_entry(
            int(plan["plan_id"]),
            1,
            {
                "mode": "leftover",
                "recipe": {"id": 11, "title": "Roast Veg"},
            },
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
        )
    )

    entry = updated["data"]["entries"][0]
    assert entry["mode"] == "leftover"
    assert entry["recipe"] is None
    assert entry["extra_recipes"] == []

    rows = list(client.meal_plan_rows.values())
    assert len(rows) == 1
    assert "recipe" not in rows[0]
    assert rows[0].get("title") == "Leftovers"


def test_patch_entry_recipe_removal_deletes_tracked_shopping_entries(tmp_path) -> None:
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
    plan_id = int(plan["plan_id"])

    first_sync = asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan_id,
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )
    created_recipe_updates = [row for row in first_sync["data"]["created"] if row.get("operation") == "recipe_shopping_update"]
    assert len(created_recipe_updates) == 1
    result_payload = created_recipe_updates[0].get("result")
    assert isinstance(result_payload, dict)
    assert int(result_payload.get("bulk_entries_created", 0)) > 0

    tracked_sync = state.get_meal_plan_instance_sync(plan_id)
    assert len(tracked_sync) == 1
    tracked_row = next(iter(tracked_sync.values()))
    assert isinstance(tracked_row.get("shopping_recipe_id"), int)

    asyncio.run(
        service.patch_entry(
            plan_id,
            1,
            {"mode": "empty"},
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
        )
    )

    assert client.deleted_shopping_calls == []

    remaining_recipe_entries = [
        row for row in client.shopping_entries
        if isinstance(row.get("list_recipe_data"), dict)
        and isinstance(row["list_recipe_data"].get("recipe_data"), dict)
        and row["list_recipe_data"]["recipe_data"].get("id") == 11
    ]
    assert remaining_recipe_entries == []


def test_patch_plan_rejects_bulk_entry_reconciliation(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = SparseRemoteMealPlanClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 4,
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
                },
                {
                    "entry_id": 2,
                    "day_index": 1,
                    "date": "2026-08-11",
                    "mode": "leftover",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                },
                {
                    "entry_id": 3,
                    "day_index": 2,
                    "date": "2026-08-12",
                    "mode": "takeout",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                },
                {
                    "entry_id": 4,
                    "day_index": 3,
                    "date": "2026-08-13",
                    "mode": "empty",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                },
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )
    plan_id = int(plan["plan_id"])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.patch_plan(
                plan_id,
                {"entries": plan["entries"]},
                ensure_tandoor_writes_enabled=ensure_writes_enabled,
            )
        )
    assert exc_info.value.status_code == 400
    assert client.meal_plan_rows == {}


def test_generate_shopping_sync_preserves_mode_only_rows(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "plan_token": "a" * 32,
            "start_date": "2026-08-10",
            "length_days": 2,
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
                },
                {
                    "entry_id": 2,
                    "day_index": 1,
                    "date": "2026-08-11",
                    "mode": "leftover",
                    "recipe": None,
                    "extra_recipes": [],
                    "servings": 2,
                },
            ],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )
    plan_id = int(plan["plan_id"])

    asyncio.run(service._sync_tandoor_meal_plan_rows(
        plan_id=plan_id,
        plan_payload=plan,
        ensure_tandoor_writes_enabled=ensure_writes_enabled,
        operation_name="test_seed",
    ))

    asyncio.run(
        service.generate_shopping_from_plan(
            plan_id=plan_id,
            mode="sync",
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )

    titles_after = [str(row.get("title") or "") for row in client.meal_plan_rows.values()]
    assert "Leftovers" in titles_after


def test_delete_plan_removes_tracked_shopping_before_meal_rows(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = OrderedDeleteMealClient()
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
            "entries": [],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )
    plan_id = int(plan["plan_id"])

    state.set_meal_plan_instance_sync(
        plan_id,
        {
            "entry:1:primary:recipe:11": {
                "instance_key": "entry:1:primary:recipe:11",
                "entry_id": 1,
                "recipe_id": 11,
                "role": "primary",
                "slot_index": None,
                "purpose": "meal",
                "date": "2026-08-10",
                "servings": 2,
                "meal_plan_row_id": 9,
            }
        },
    )

    client.meal_plan_rows[9] = {"id": 9, "title": "Row 9"}

    result = asyncio.run(service.delete_plan(plan_id, ensure_tandoor_writes_enabled=ensure_writes_enabled))

    assert result["data"]["deleted"] is True
    assert client.call_order == ["meal:9"]
    assert state.get_meal_plan(plan_id) is None


def test_sync_from_tandoor_updates_tracked_entry(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)
    plan = state.create_meal_plan(
        {
            "plan_token": "a" * 32,
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
            "entries": [
                {
                    "entry_id": 1,
                    "day_index": 0,
                    "date": "2026-08-10",
                    "mode": "planned",
                    "recipe": {"id": 11, "title": "Old recipe"},
                    "extra_recipes": [],
                    "servings": 2,
                }
            ],
        }
    )
    plan_id = int(plan["plan_id"])
    state.set_meal_plan_instance_sync(
        plan_id,
        {
            "entry:1:primary:recipe:11": {
                "instance_key": "entry:1:primary:recipe:11",
                "entry_id": 1,
                "recipe_id": 11,
                "role": "primary",
                "slot_index": None,
                "purpose": "meal",
                "date": "2026-08-10",
                "servings": 2,
                "meal_plan_row_id": 9,
            }
        },
    )
    client.meal_plan_rows[9] = {
        "id": 9,
        "recipe": {"id": 22, "name": "New recipe"},
        "from_date": "2026-08-10T18:00:00Z",
        "servings": 4,
        "note": "wfd-plan:" + ("a" * 32) + ";wfd-instance:entry:1:primary:recipe:11",
    }

    result = asyncio.run(service.sync_from_tandoor())

    updated = state.get_meal_plan(plan_id)
    assert result["changed_plan_ids"] == [plan_id]
    assert result["changed_dates"] == []
    assert updated["entries"][0]["recipe"]["id"] == 22
    assert updated["entries"][0]["servings"] == 4


def test_sync_from_tandoor_keeps_unmarked_rows_unfiled(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = FakeMealClient()
    service = MealPlanService(state, client)
    plans = []
    for plan_id in range(2):
        plans.append(
            state.create_meal_plan(
                {
                    "start_date": "2026-08-10",
                    "length_days": 1,
                    "diners": 2,
                    "entries": [
                        {
                            "entry_id": plan_id + 1,
                            "day_index": 0,
                            "date": "2026-08-10",
                            "mode": "planned",
                            "recipe": None,
                            "extra_recipes": [],
                            "servings": 2,
                        }
                    ],
                }
            )
        )
    client.meal_plan_rows[77] = {
        "id": 77,
        "recipe": {"id": 33, "name": "Salad"},
        "from_date": "2026-08-10T18:00:00Z",
        "servings": 2,
    }
    client.meal_plan_rows[78] = {
        "id": 78,
        "recipe": {"id": 33, "name": "Salad"},
        "from_date": "2026-08-10T18:00:00Z",
        "servings": 2,
    }

    first = asyncio.run(service.sync_from_tandoor())
    second = asyncio.run(service.sync_from_tandoor())

    plan_ids = sorted(int(plan["plan_id"]) for plan in plans)
    assert first["changed_plan_ids"] == []
    assert second["changed_plan_ids"] == []
    first_plan = state.get_meal_plan(plan_ids[0])
    second_plan = state.get_meal_plan(plan_ids[1])
    assert first_plan["entries"][0]["recipe"] is None
    assert second_plan["entries"][0]["recipe"] is None

    client.meal_plan_rows[77]["recipe"] = {"id": 44, "name": "Updated salad"}
    changed = asyncio.run(service.sync_from_tandoor())
    assert changed["changed_plan_ids"] == []
    assert client.meal_plan_rows[77]["recipe"]["id"] == 44


def test_sync_from_tandoor_rebuilds_stale_shopping_rows(tmp_path) -> None:
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
                    "recipe": {"id": 11, "title": "Old recipe"},
                    "extra_recipes": [],
                    "servings": 2,
                }
            ],
        }
    )
    plan_id = int(plan["plan_id"])
    state.set_meal_plan_instance_sync(
        plan_id,
        {
            "entry:1:primary:recipe:11": {
                "instance_key": "entry:1:primary:recipe:11",
                "entry_id": 1,
                "recipe_id": 11,
                "recipe_title": "Old recipe",
                "role": "primary",
                "slot_index": None,
                "purpose": "meal",
                "date": "2026-08-10",
                "servings": 2,
                "meal_plan_row_id": 9,
                "shopping_recipe_id": 1,
                "shopping_activated": True,
            }
        },
    )
    client.meal_plan_rows[9] = {
        "id": 9,
        "recipe": {"id": 22, "name": "New recipe"},
        "from_date": "2026-08-10T18:00:00Z",
        "servings": 2,
        "note": "wfd-plan:" + ("a" * 32) + ";wfd-instance:entry:1:primary:recipe:11",
    }
    client.shopping_recipe_rows[1] = {"id": 1, "recipe": 11, "mealplan": 9, "servings": 2}
    client.shopping_entries.append(
        {
            "id": 8,
            "shopping_recipe_id": 1,
            "list_recipe_data": {"recipe_data": {"id": 11, "name": "Old recipe"}},
        }
    )

    result = asyncio.run(
        service.sync_from_tandoor(
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )

    assert result["shopping_sync"] == []
    assert client.deleted_shopping_calls == []
    assert client.shopping_recipe_rows[1]["recipe"] == 11


def test_sync_from_tandoor_does_not_recreate_deleted_remote_meal(tmp_path) -> None:
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
                    "recipe": {"id": 11, "title": "Old recipe"},
                    "extra_recipes": [],
                    "servings": 2,
                }
            ],
        }
    )
    plan_id = int(plan["plan_id"])
    state.set_meal_plan_instance_sync(
        plan_id,
        {
            "entry:1:primary:recipe:11": {
                "instance_key": "entry:1:primary:recipe:11",
                "entry_id": 1,
                "recipe_id": 11,
                "role": "primary",
                "slot_index": None,
                "purpose": "meal",
                "date": "2026-08-10",
                "servings": 2,
                "meal_plan_row_id": 9,
            }
        },
    )
    client.meal_plan_rows[9] = {
        "id": 9,
        "recipe": {"id": 11, "name": "Old recipe"},
        "from_date": "2026-08-10T18:00:00Z",
        "servings": 2,
        "note": "wfd-plan:" + ("a" * 32) + ";wfd-instance:entry:1:primary:recipe:11",
    }
    del client.meal_plan_rows[9]

    asyncio.run(
        service.sync_from_tandoor(
            ensure_tandoor_writes_enabled=ensure_writes_enabled,
            build_shopping_view=build_shopping_view,
        )
    )

    assert client.meal_plan_rows == {}
    updated = state.get_meal_plan(plan_id)
    assert updated["entries"] == []


def test_delete_plan_aborts_when_shopping_cleanup_fails(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = OrderedDeleteMealClient(fail_shopping_ids={502})
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
            "entries": [],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )
    plan_id = int(plan["plan_id"])

    state.set_meal_plan_instance_sync(
        plan_id,
        {
            "entry:1:primary:recipe:11": {
                "instance_key": "entry:1:primary:recipe:11",
                "entry_id": 1,
                "recipe_id": 11,
                "role": "primary",
                "slot_index": None,
                "purpose": "meal",
                "date": "2026-08-10",
                "servings": 2,
                "meal_plan_row_id": 9,
            }
        },
    )

    client.meal_plan_rows[9] = {"id": 9, "title": "Row 9"}

    result = asyncio.run(service.delete_plan(plan_id, ensure_tandoor_writes_enabled=ensure_writes_enabled))

    assert result["data"]["deleted"] is True
    assert client.call_order == ["meal:9"]
    assert state.get_meal_plan(plan_id) is None
    assert state.get_meal_plan_instance_sync(plan_id) == {}
    assert 9 not in client.meal_plan_rows


def test_delete_plan_treats_missing_shopping_entries_as_already_removed(tmp_path) -> None:
    state = Stage2State(str(tmp_path))
    client = OrderedDeleteMealClient(missing_shopping_ids={502})
    service = MealPlanService(state, client)

    plan = state.create_meal_plan(
        {
            "start_date": "2026-08-10",
            "length_days": 1,
            "diners": 2,
            "entries": [],
            "keyword_ids": [],
            "constraints": {"leftover_days": [], "takeout_days": [], "empty_days": []},
            "no_repeat_days": 30,
        }
    )
    plan_id = int(plan["plan_id"])

    state.set_meal_plan_instance_sync(
        plan_id,
        {
            "entry:1:primary:recipe:11": {
                "instance_key": "entry:1:primary:recipe:11",
                "entry_id": 1,
                "recipe_id": 11,
                "role": "primary",
                "slot_index": None,
                "purpose": "meal",
                "date": "2026-08-10",
                "servings": 2,
                "meal_plan_row_id": 9,
            }
        },
    )

    client.meal_plan_rows[9] = {"id": 9, "title": "Row 9"}

    result = asyncio.run(service.delete_plan(plan_id, ensure_tandoor_writes_enabled=ensure_writes_enabled))

    assert result["data"]["deleted"] is True
    assert client.call_order == ["meal:9"]
    assert state.get_meal_plan(plan_id) is None
