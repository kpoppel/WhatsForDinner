import asyncio

import httpx

from app.services.tandoor_client import TandoorClient


def test_list_tags_calls_keyword_endpoint(monkeypatch) -> None:
    called: dict[str, str] = {}

    async def fake_get(path: str, params=None):
        called["path"] = path
        return {"results": []}

    client = TandoorClient()
    monkeypatch.setattr(client, "_get", fake_get)

    asyncio.run(client.list_tags())
    assert called["path"] == "/api/keyword/"


def test_requests_reuse_transport_and_close_it(monkeypatch) -> None:
    transports = []

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.requests = 0
            self.closed = False
            transports.append(self)

        async def request(self, **kwargs):
            self.requests += 1
            return httpx.Response(
                200,
                json={"results": []},
                request=httpx.Request(kwargs["method"], kwargs["url"]),
            )

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    async def exercise():
        client = TandoorClient()
        await client.list_tags()
        await client.list_tags()
        await client.aclose()

    asyncio.run(exercise())
    assert len(transports) == 1
    assert transports[0].requests == 2
    assert transports[0].closed