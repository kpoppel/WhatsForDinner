from app.services.tandoor_client import TandoorClient


def test_list_tags_calls_keyword_endpoint(monkeypatch) -> None:
    called: dict[str, str] = {}

    async def fake_get(path: str, params=None):
        called["path"] = path
        return {"results": []}

    client = TandoorClient()
    monkeypatch.setattr(client, "_get", fake_get)

    import asyncio

    asyncio.run(client.list_tags())
    assert called["path"] == "/api/keyword/"