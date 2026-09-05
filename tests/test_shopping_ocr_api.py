"""Shopping-list OCR API validation and provider-error tests."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_shopping_list_ocr_requires_configured_api_key(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.google_llm_api_key", "")

    response = client.post(
        "/api/v1/shopping-list/ocr",
        files={"image": ("list.jpg", b"fake-bytes", "image/jpeg")},
    )

    assert response.status_code == 503


def test_shopping_list_ocr_rejects_non_image_upload(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.google_llm_api_key", "test-key")

    response = client.post(
        "/api/v1/shopping-list/ocr",
        files={"image": ("list.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400


def test_shopping_list_ocr_returns_parsed_items(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.google_llm_api_key", "test-key")

    class FakeOcrClient:
        async def transcribe_handwritten_list(self, image_bytes, mime_type):
            return "- Milk\n* Eggs\n\nBread\n"

    monkeypatch.setattr("app.api._ocr_client", lambda: FakeOcrClient())

    response = client.post(
        "/api/v1/shopping-list/ocr",
        files={"image": ("list.jpg", b"fake-bytes", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {"items": ["Milk", "Eggs", "Bread"]}


def test_shopping_list_ocr_returns_502_on_ocr_error(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.google_llm_api_key", "test-key")

    from app.services.ocr_client import OcrError

    class FailingOcrClient:
        async def transcribe_handwritten_list(self, image_bytes, mime_type):
            raise OcrError("boom")

    monkeypatch.setattr("app.api._ocr_client", lambda: FailingOcrClient())

    response = client.post(
        "/api/v1/shopping-list/ocr",
        files={"image": ("list.jpg", b"fake-bytes", "image/jpeg")},
    )

    assert response.status_code == 502
