"""Turn a page image into clean text using a vision-capable Claude model."""

from __future__ import annotations

import base64
import io

import anthropic
from PIL.Image import Image

from .prompts import SYSTEM_PROMPT

_MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg"}


class Transcriber:
    def __init__(
        self,
        model: str,
        max_tokens: int,
        image_format: str = "PNG",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        # max_retries gives us exponential backoff on 429/5xx for free across a long run.
        self.client = client or anthropic.Anthropic(max_retries=4)
        self.model = model
        self.max_tokens = max_tokens
        self.image_format = image_format

    def _encode(self, image: Image) -> str:
        buffer = io.BytesIO()
        if self.image_format == "JPEG":
            image = image.convert("RGB")
            image.save(buffer, format="JPEG", quality=95)
        else:
            image.save(buffer, format="PNG")
        return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    def transcribe(self, image: Image) -> str:
        data = self._encode(image)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _MEDIA_TYPES[self.image_format],
                                "data": data,
                            },
                        },
                        {"type": "text", "text": "Transcribe this page."},
                    ],
                }
            ],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
