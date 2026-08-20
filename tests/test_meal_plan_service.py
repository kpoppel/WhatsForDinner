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
            "steps": [{"ingredients": [{"id": 100 + recipe_id}, {"id": 101 + recipe_id}]}],
            "ingredients": [{"id": 999}],
        }

    async def update_recipe_shopping(self, recipe_id, payload):
        self.updated_shopping_calls.append((recipe_id, payload))
        return {"ok": True, "recipe_id": recipe_id, "payload": payload}

    async def list_shopping_entries(self, limit=100):
        return {
            "results": [
                {
                    "id": 1,
                    "food": {"name": "Carrot", "category": "Vegetables"},
                    "amount": 2,
                    "checked": False,
                }
            ]
        }


class BrokenMealClient(FakeMealClient):
    async def list_recipes(self, search=None, limit=20, keyword_ids=None):
        raise TandoorError("recipes unavailable")


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
    assert len(data["created"]) == 1
    assert len(data["failed"]) == 1
    assert data["created"][0]["entry_id"] == 1
    assert data["failed"][0]["entry_id"] == 2
    assert data["shopping_view"]["count"] == 1


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
