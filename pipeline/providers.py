"""Image providers: the plug-in slot from docs/stages.md."""
import hashlib
import os
import time
from io import BytesIO
from typing import Protocol

import httpx
from PIL import Image, ImageDraw

SIZE = (1024, 1024)


class ImageProvider(Protocol):
    name: str
    model: str | None  # recorded in the manifest for generated heroes
    resolution: str | None

    def generate(self, prompt: str) -> Image.Image: ...


class MockProvider:
    """Deterministic, offline stand-in: same prompt -> same pixels."""

    name = "mock"
    model = resolution = None  # ignores both: output is always SIZE

    def generate(self, prompt: str) -> Image.Image:
        # Flat two-tone set, can on a plinth, laid out like the prompt's COMPOSITION line.
        # No text: the spec's AI image never contains any. hashlib, not hash() (salted per process).
        d = hashlib.sha256(prompt.encode("utf-8")).digest()
        wall, floor, can = tuple(d[0:3]), tuple(d[3:6]), tuple(d[6:9])
        w, h = SIZE
        img = Image.new("RGB", SIZE, wall)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, h * 0.60, w, h), fill=floor)
        cx, cw = w / 2, w * 0.25
        draw.rectangle((cx - cw * 0.6, h * 0.62, cx + cw * 0.6, h * 0.70),
                       fill=tuple(v // 2 for v in floor))  # plinth, a darker floor tone
        draw.rounded_rectangle((cx - cw / 2, h * 0.20, cx + cw / 2, h * 0.62),
                               radius=cw / 6, fill=can)
        return img


API = "https://api.elevenlabs.io/v1/flows/image"
# Both accept aspect_ratio "1:1" and resolution 1K/2K/4K; neither takes a seed (API docs, 2026-09).
MODELS = {"gemini-3-pro-image": "Nano Banana Pro", "gpt-image-2.5-sunburst": "GPT Image 2.5 Sunburst"}
DEFAULT_MODEL = "gemini-3-pro-image"
# 2K: no ratio crops any more; each scales the 1:1 hero to 1080 px per side (9:16 by width,
# 16:9 by height), so 2K downsamples with headroom. A 1K (1024 px) hero would be upscaled ~1.05x.
DEFAULT_RESOLUTION = "2K"


class ProviderError(RuntimeError):
    """A provider failed. Messages are safe to print: they never contain the key."""


class ElevenLabsProvider:
    """ElevenLabs Flows image API: submit, poll until done, download."""

    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 resolution: str = DEFAULT_RESOLUTION, client: httpx.Client | None = None,
                 poll_interval: float = 2.0, timeout: float = 120.0, sleep=time.sleep):
        if model not in MODELS:  # before any request: a typo costs $0
            raise ProviderError(f"Unknown model {model!r}; choose from {', '.join(MODELS)}")
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise ProviderError("ELEVENLABS_API_KEY is not set (add it to .env)")
        self._headers = {"xi-api-key": key}
        self.model, self.resolution = model, resolution
        self._client = client or httpx.Client(timeout=30.0)
        self.poll_interval, self.timeout, self._sleep = poll_interval, timeout, sleep

    def generate(self, prompt: str) -> Image.Image:
        # 1:1 explicitly: both models default to 16:9, and fit_to_ratio fits every ratio from a square hero.
        # No quality field: Sunburst keeps its default ("high"); Nano Banana Pro has none.
        body = {"model_id": self.model, "prompt": prompt, "aspect_ratio": "1:1",
                "resolution": self.resolution}
        gen_id = self._call("POST", API, json=body)["id"]
        waited = 0.0
        while True:
            self._sleep(self.poll_interval)  # docs: at least 2s between polls
            waited += self.poll_interval
            gen = self._call("GET", f"{API}/{gen_id}")
            if gen["status"] == "completed":
                break
            if gen["status"] == "failed":
                raise ProviderError(f"ElevenLabs generation failed "
                                    f"({gen.get('failure_reason')}): {gen.get('error_message')}")
            if waited >= self.timeout:
                raise ProviderError(f"ElevenLabs generation {gen_id} not done after {self.timeout:.0f}s")
        # Signed URL: no key header, so the key never leaves api.elevenlabs.io.
        content = self._send("GET", gen["content_url"]).content
        return Image.open(BytesIO(content)).convert("RGB")

    def _call(self, method: str, url: str, **kwargs) -> dict:
        return self._send(method, url, headers=self._headers, **kwargs).json()

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.TransportError as err:  # DNS, connection, and timeout failures
            what = "timed out" if isinstance(err, httpx.TimeoutException) else "network error"
            # from None: our message is enough, and the chained exception carries the request.
            raise ProviderError(f"ElevenLabs request {what} ({type(err).__name__}); "
                                "check your connection and retry") from None
        _check(resp)
        return resp


HINTS = {
    401: "API key rejected (check ELEVENLABS_API_KEY)",
    402: "plan or credits: the Image & Video API needs a Pro plan or above",
    403: "API key lacks the Image & Video / Flows permission (or IP not allowlisted)",
    429: "rate limited by ElevenLabs; retry later",
}


def _check(resp: httpx.Response) -> None:
    """Raise ProviderError for 4xx/5xx using the {"detail": {...}} error shape."""
    if resp.status_code < 400:
        return
    try:
        detail = resp.json().get("detail")
    except (ValueError, AttributeError):  # non-JSON body, or JSON that isn't an object
        detail = None
    info = detail if isinstance(detail, dict) else {}
    code = f" [{info['code']}]" if info.get("code") else ""
    hint = HINTS.get(resp.status_code) or info.get("message") or resp.reason_phrase
    raise ProviderError(f"ElevenLabs HTTP {resp.status_code}{code}: {hint}")
