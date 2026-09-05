"""Tandoor transport authentication, pooling, and error-normalization tests."""

import asyncio

import httpx

from app.services.tandoor_client import TandoorClient
from app.services.tandoor_client import TandoorError


def test_list_tags_calls_keyword_endpoint(monkeypatch) -> None:
    called: dict[str, str] = {}

    async def fake_get(path: str, params=None):
        called["path"] = path
        return {"results": []}

    client = TandoorClient()
    monkeypatch.setattr(client, "_get", fake_get)

    asyncio.run(client.list_tags())
    assert called["path"] == "/api/keyword/"


def test_request_normalizes_upstream_http_error(monkeypatch) -> None:
    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def request(self, method, url, params=None, json=None, headers=None):
            request = httpx.Request(method, url)
            return httpx.Response(429, request=request, text="rate limited")

    monkeypatch.setattr("app.services.tandoor_client.httpx.AsyncClient", FakeAsyncClient)

    client = TandoorClient()

    try:
        asyncio.run(client.list_tags())
    except TandoorError as exc:
        assert "Tandoor returned 429" in str(exc)
        assert "rate limited" in str(exc)
    else:
        raise AssertionError("Expected TandoorError for upstream HTTP failure")


def test_requests_reuse_one_http_client(monkeypatch) -> None:
    instances = []

    class FakeResponse:
        content = b'{"results": []}'
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class FakeAsyncClient:
        def __init__(self, timeout):
            instances.append(self)

        async def request(self, method, url, params=None, json=None, headers=None):
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr("app.services.tandoor_client.httpx.AsyncClient", FakeAsyncClient)

    client = TandoorClient()
    asyncio.run(client.list_tags())
    asyncio.run(client.list_meal_types())
    asyncio.run(client.close())

    assert len(instances) == 1