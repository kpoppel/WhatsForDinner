from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config import settings

TRANSCRIBE_PROMPT = (
    "Transcribe the handwritten text in this image line by line. "
    "Output ONLY a clean list of items, one per line. "
    "Do not include markdown bullet points, intro, or outro."
)


class OcrError(RuntimeError):
    """Raised when the OCR provider cannot be reached or returns an error."""


class GeminiOcrClient:
    def __init__(self) -> None:
        self.api_key = settings.google_llm_api_key
        self.model = settings.google_llm_model
        self.timeout = settings.google_llm_timeout_seconds

    async def transcribe_handwritten_list(self, image_bytes: bytes, mime_type: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                        {"text": TRANSCRIBE_PROMPT},
                    ]
                }
            ]
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()
            body_snippet = body[:300] if body else ""
            raise OcrError(
                f"Gemini returned {exc.response.status_code} for OCR request."
                + (f" Response: {body_snippet}" if body_snippet else "")
            ) from exc
        except httpx.HTTPError as exc:
            raise OcrError("Unable to reach Gemini OCR endpoint.") from exc

        return self._extract_text(data)

    @staticmethod
    def _extract_text(data: Any) -> str:
        try:
            candidates = data["candidates"]
            parts = candidates[0]["content"]["parts"]
            text = parts[0]["text"].lower()
        except (KeyError, IndexError, TypeError) as exc:
            raise OcrError("Gemini response did not contain transcribed text.") from exc
        if not isinstance(text, str):
            raise OcrError("Gemini response text was not a string.")
        return text
