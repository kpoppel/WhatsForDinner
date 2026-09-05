"""Strict browser-facing request and response contracts.

Mutation models forbid unknown fields so contract drift fails at the API
boundary instead of being silently ignored by services or Tandoor adapters.
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

TIME_24H_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class SetSelectedKeywordsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword_ids: list[int]


class MealPlanRulesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_repeat_days: int = Field(ge=0)


class UserSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_diners: int = Field(ge=1, le=20)
    default_notification_time: str

    @model_validator(mode="after")
    def validate_time(self) -> "UserSettingsRequest":
        if TIME_24H_RE.match(self.default_notification_time.strip()) is None:
            raise ValueError("default_notification_time must be HH:MM (24-hour).")
        return self


class MealPlanConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leftover_days: list[int | str] = Field(default_factory=list)
    takeout_days: list[int | str] = Field(default_factory=list)
    empty_days: list[int | str] = Field(default_factory=list)


class GenerateMealPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    length_days: int = Field(default=7, ge=1, le=31)
    diners: int | None = Field(default=None, ge=1, le=20)
    constraints: MealPlanConstraints = Field(default_factory=MealPlanConstraints)
    keyword_ids: list[int] | None = None
    no_repeat_days: int | None = Field(default=None, ge=0)


class MealPlanPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: str | None = None
    length_days: int | None = None
    diners: int | None = None
    constraints: MealPlanConstraints | None = None
    keyword_ids: list[int] | None = None
    entries: list[dict[str, Any]] | None = None


class MealPlanEntryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_index: int | None = None
    date: str | None = None
    mode: str | None = None
    recipe: dict[str, Any] | None = None
    extra_recipes: list[dict[str, Any]] | None = None
    servings: int | None = None
    reminder_enabled: bool | None = None
    reminder_text: str | None = None
    notes: str | None = None


class MealPlanEntryPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_index: int | None = None
    date: str | None = None
    mode: str | None = None
    recipe: dict[str, Any] | None = None
    extra_recipes: list[dict[str, Any]] | None = None
    servings: int | None = None
    reminder_enabled: bool | None = None
    reminder_text: str | None = None
    notes: str | None = None
    target_day_index: int | None = None


class ShoppingEntryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ad_hoc: bool | None = None
    status: str | None = None
    reminder_enabled: bool | None = None
    reminder_date: str | None = None
    reminder_text: str | None = None
    name: str | None = None
    amount: int | float | None = None
    unit: str | None = None
    ingredient_type: str | None = None
    recipe_context: str | None = None
    food_id: int | None = None
    recipe: dict[str, Any] | None = None
    store_group: dict[str, Any] | str | int | None = None
    food: dict[str, Any] | None = None
    checked: bool | None = None
    delay_until: str | None = None


class ShoppingEntryPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    reminder_enabled: bool | None = None
    reminder_date: str | None = None
    reminder_text: str | None = None
    name: str | None = None
    amount: int | float | None = None
    unit: str | None = None
    ingredient_type: str | None = None
    recipe_context: str | None = None
    store_group: dict[str, Any] | str | int | None = None
    food: dict[str, Any] | None = None
    checked: bool | None = None
    delay_until: str | None = None


class SyncOperation(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"


class ShoppingSyncChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: SyncOperation
    entry_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    queued_at: str | None = None

    @model_validator(mode="after")
    def validate_entry_id(self) -> "ShoppingSyncChange":
        if self.operation in {SyncOperation.update, SyncOperation.delete} and self.entry_id is None:
            raise ValueError("entry_id is required for update and delete operations.")
        return self


class ShoppingSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[ShoppingSyncChange]


class ShoppingListOcrResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str]
