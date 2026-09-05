"""Legacy Stage 1 API compatibility and application-route tests."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def setup_module(module) -> None:
    from app import api as api_module

    api_module.settings.tandoor_write_enabled = True


def test_health_route() -> None:
    """Verify the health endpoint exposes the expected liveness payload."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_versioned_openapi_schema_route() -> None:
    """Verify the versioned OpenAPI schema remains available."""
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["openapi"].startswith("3.")
    assert payload["info"]["title"] == "WhatsForDinner"


def test_versioned_docs_routes() -> None:
    """Verify Swagger and ReDoc are served under the versioned API prefix."""
    swagger_response = client.get("/api/v1/docs")
    assert swagger_response.status_code == 200
    assert "/api/v1/openapi.json" in swagger_response.text

    redoc_response = client.get("/api/v1/redoc")
    assert redoc_response.status_code == 200
    assert "/api/v1/openapi.json" in redoc_response.text


def test_recipes_route_uses_tandoor_payload(monkeypatch) -> None:
    """Verify recipe search forwards upstream data through normalization."""
    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {
                "count": 1,
                "results": [{"id": 1, "name": "Pasta", "tags": ["quick", "family"]}],
            }

    monkeypatch.setattr("app.api.client", FakeClient())

    response = client.get("/api/v1/recipes?search=pasta&limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "tandoor"
    assert payload["data"]["results"][0]["name"] == "Pasta"


def test_recipes_route_forwards_keyword_ids(monkeypatch) -> None:
    """Verify keyword filters reach the Tandoor recipe client."""
    captured: dict[str, object] = {}

    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            captured["search"] = search
            captured["limit"] = limit
            captured["keyword_ids"] = keyword_ids
            return {"results": []}

    monkeypatch.setattr("app.api.client", FakeClient())

    response = client.get("/api/v1/recipes?limit=7&keyword_ids=12&keyword_ids=18")
    assert response.status_code == 200
    assert captured["search"] is None
    assert captured["limit"] == 7
    assert captured["keyword_ids"] == [12, 18]


def test_recipe_tags_route_returns_list(monkeypatch) -> None:
    """Verify recipe tags are exposed as a stable list response."""
    class FakeClient:
        async def list_tags(self):
            return [{"id": 1, "name": "Quick"}, {"id": 2, "name": "Family"}]

    monkeypatch.setattr("app.api.client", FakeClient())

    response = client.get("/api/v1/recipe-tags")
    assert response.status_code == 200
    assert response.json()["data"][0]["name"] == "Quick"


def test_today_meal_route_returns_structured_payload(monkeypatch) -> None:
    """Verify today's meal route returns recipe and ingredient structure."""
    class FakeClient:
        async def list_recipes(self, search=None, limit=20, keyword_ids=None):
            return {
                "results": [
                    {
                        "id": 42,
                        "name": "Chicken Curry"
                    }
                ]
            }

        async def get_recipe(self, recipe_id):
            assert recipe_id == 42
            return {
                "id": 42,
                "name": "Chicken Curry",
                "steps": [
                    {
                        "instruction": "Cook the chicken.",
                        "ingredients": [
                            {"amount": "2", "unit": {"name": "cloves"}, "food": {"name": "garlic"}},
                            {"amount": "1", "unit": {"name": "tbsp"}, "food": {"name": "oil"}},
                        ],
                    }
                ],
            }

    monkeypatch.setattr("app.api.client", FakeClient())

    response = client.get("/api/v1/today-meal")
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Chicken Curry"
    assert payload["ingredients"][0]["name"] == "garlic"
    assert payload["steps"][0]["instruction"] == "Cook the chicken."


def test_shopping_entry_write_routes(monkeypatch) -> None:
    """Verify legacy shopping write routes delegate to the Tandoor client."""
    class FakeClient:
        async def create_shopping_entry(self, payload):
            return {"id": 5, **payload}

        async def update_shopping_entry(self, entry_id, payload):
            return {"id": entry_id, **payload}

        async def delete_shopping_entry(self, entry_id):
            return {"deleted": entry_id}

    monkeypatch.setattr("app.api.client", FakeClient())

    create_payload = {
        "food": {"name": "Milk"},
        "amount": 1,
    }
    create_res = client.post("/api/v1/shopping-list/entries", json=create_payload)
    assert create_res.status_code == 200
    assert create_res.json()["data"]["id"] == 5

    patch_res = client.patch("/api/v1/shopping-list/entries/5", json={"checked": True})
    assert patch_res.status_code == 200
    assert patch_res.json()["data"]["checked"] is True

    delete_res = client.delete("/api/v1/shopping-list/entries/5")
    assert delete_res.status_code == 200
    assert delete_res.json()["data"]["deleted"] == 5


def test_rudimentary_user_app_route() -> None:
    """Verify the unified user application shell is routable."""
    response = client.get("/app")
    assert response.status_code == 200
    assert "WhatsForDinner" in response.text
    assert "Shopping Mode" in response.text
    assert "window.WFD_PERFORMANCE_METRICS_ENABLED = false;" in response.text


def test_api_response_exposes_timing_and_correlation_headers() -> None:
    """Verify API middleware exposes correlation and timing response headers."""
    response = client.get("/api/v1/health", headers={"X-Correlation-ID": "phase6-test"})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "phase6-test"
    assert float(response.headers["X-Request-Duration-Ms"]) >= 0
    assert response.headers["Server-Timing"].startswith("app;dur=")


def test_standalone_shopping_app_route_removed() -> None:
    """Verify the deprecated standalone shopping route remains unavailable."""
    response = client.get("/shopping")
    assert response.status_code == 404
