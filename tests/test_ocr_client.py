"""Gemini OCR transport request, response, and failure contract tests."""

import asyncio

import httpx
import pytest

from app.services.ocr_client import GeminiOcrClient, OcrError


def test_transcribe_handwritten_list_parses_gemini_response(monkeypatch) -> None:
    client = GeminiOcrClient()

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Milk\nEggs\nBread"}]}}
                ]
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    text = asyncio.run(client.transcribe_handwritten_list(b"fake-bytes", "image/jpeg"))
    assert text == "milk\neggs\nbread"


def test_transcribe_handwritten_list_raises_ocr_error_on_malformed_response(monkeypatch) -> None:
    client = GeminiOcrClient()

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": []}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(OcrError):
        asyncio.run(client.transcribe_handwritten_list(b"fake-bytes", "image/jpeg"))


def test_transcribe_handwritten_list_raises_ocr_error_on_http_error(monkeypatch) -> None:
    client = GeminiOcrClient()

    class FakeResponse:
        status_code = 500
        text = "server error"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("boom", request=None, response=self)

        def json(self):
            return {}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(OcrError):
        asyncio.run(client.transcribe_handwritten_list(b"fake-bytes", "image/jpeg"))
