from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CURRENT_STATE_SCHEMA_VERSION = 11


class MealPlanRulesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_repeat_days: int


class UserSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_diners: int
    default_notification_time: str


class ShoppingInstanceSyncRowModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_key: str
    entry_id: int
    recipe_id: int | None = None
    recipe_title: str | None = None
    role: Literal["primary", "extra"]
    slot_index: int | None = None
    purpose: str | None = None
    date: str
    servings: int
    meal_plan_row_id: int | None = None
    shopping_recipe_id: int | None = None
    shopping_activated: bool = False


class MealPlanInstanceSyncModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instances: dict[str, ShoppingInstanceSyncRowModel] = Field(default_factory=dict)


class RecipeUseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: int
    used_date: str
    plan_id: int
    entry_id: int


class PendingShoppingChangeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["create", "update", "delete"]
    entry_id: int | None = None
    payload: dict[str, Any]


class ServerStateDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[11]
    selected_keyword_ids: list[int]
    meal_plan_rules: MealPlanRulesModel
    user_settings: UserSettingsModel
    meal_plans: dict[str, dict[str, Any]]
    next_meal_plan_id: int
    next_entry_id: int
    shopping_status_overrides: dict[str, str]
    shopping_item_metadata: dict[str, dict[str, Any]]
    local_shopping_entries: dict[str, dict[str, Any]]
    next_local_shopping_entry_id: int
    meal_plan_instance_sync: dict[str, MealPlanInstanceSyncModel] = Field(default_factory=dict)
    recipe_use_history: list[RecipeUseModel] = Field(default_factory=list)
    pending_shopping_changes: dict[str, PendingShoppingChangeModel] = Field(default_factory=dict)


def default_state_payload() -> dict[str, Any]:
    return {
        "schema_version": CURRENT_STATE_SCHEMA_VERSION,
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
        "pending_shopping_changes": {},
    }
