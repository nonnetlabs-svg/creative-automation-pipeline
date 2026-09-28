import io
import json

import httpx
import pytest
from PIL import Image

from pipeline.providers import (
    DEFAULT_MODEL, DEFAULT_RESOLUTION, MODELS, ElevenLabsProvider, MockProvider, ProviderError,
)

KEY = "sk-fake-test-key"  # never a real key; asserted absent from every error message

CORNER = (1023, 1023)  # far from the text, so it's pure background


def test_same_prompt_identical_pixels():
    a = MockProvider().generate("sparkling lime soda in a green aluminum can")
    b = MockProvider().generate("sparkling lime soda in a green aluminum can")
    assert a.tobytes() == b.tobytes()


def test_different_prompts_different_colors():
    a = MockProvider().generate("sparkling lime soda in a green aluminum can")
    b = MockProvider().generate("mixed berry soda in a purple aluminum can")
    assert a.getpixel(CORNER) != b.getpixel(CORNER)


def test_size_is_1024():
    assert MockProvider().generate("any prompt").size == (1024, 1024)


def test_name_is_mock():
    assert MockProvider().name == "mock"


# --- ElevenLabs: fake server via httpx.MockTransport, no real API calls ---

def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), "red").save(buf, "PNG")  # RGBA on purpose: provider must return RGB
    return buf.getvalue()


def eleven(handler, **kwargs) -> ElevenLabsProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ElevenLabsProvider(api_key=KEY, client=client, sleep=lambda s: None, **kwargs)


def raises_safely(provider, match: str) -> None:
    with pytest.raises(ProviderError, match=match) as err:
        provider.generate("lime soda")
    assert KEY not in str(err.value)


def test_elevenlabs_submit_poll_download():
    seen, polls = [], iter(["pending", "generating", "completed"])

    def handler(req):
        seen.append(req)
        if req.method == "POST":
            return httpx.Response(200, json={"id": "gen1", "status": "pending"})
        if req.url.host == "api.elevenlabs.io":
            body = {"id": "gen1", "status": next(polls)}
            if body["status"] == "completed":
                body |= {"content_mime_type": "image/png", "content_url": "https://cdn.test/gen1.png"}
            return httpx.Response(200, json=body)
        return httpx.Response(200, content=png_bytes())

    img = eleven(handler).generate("lime soda")
    assert (img.mode, img.size) == ("RGB", (8, 8))
    assert json.loads(seen[0].content) == {
        "model_id": "gemini-3-pro-image", "prompt": "lime soda", "aspect_ratio": "1:1",
        "resolution": "2K"}
    assert [r.url.path for r in seen[1:4]] == ["/v1/flows/image/gen1"] * 3
    assert all(r.headers["xi-api-key"] == KEY for r in seen[:4])
    assert "xi-api-key" not in seen[4].headers  # key never sent to the download host


@pytest.mark.parametrize("model", list(MODELS))
def test_elevenlabs_body_per_model(model):
    bodies = []

    def handler(req):
        if req.method == "POST":
            bodies.append(json.loads(req.content))
            return httpx.Response(200, json={"id": "gen1", "status": "pending"})
        if req.url.host == "api.elevenlabs.io":
            return httpx.Response(200, json={"id": "gen1", "status": "completed",
                                             "content_url": "https://cdn.test/gen1.png"})
        return httpx.Response(200, content=png_bytes())

    provider = eleven(handler, model=model)
    provider.generate("lime soda")
    # Exact match: no seed, no quality, nothing the model doesn't support.
    assert bodies == [{"model_id": model, "prompt": "lime soda", "aspect_ratio": "1:1",
                       "resolution": DEFAULT_RESOLUTION}]
    assert (provider.model, provider.resolution) == (model, "2K")


def test_elevenlabs_unknown_model_fails_before_any_request():
    calls = []
    with pytest.raises(ProviderError, match="Unknown model 'gemini-2.5-flash-image'"):
        eleven(lambda req: calls.append(req), model="gemini-2.5-flash-image")
    assert calls == []


def test_default_is_nano_banana_pro_2k():
    assert (DEFAULT_MODEL, DEFAULT_RESOLUTION) == ("gemini-3-pro-image", "2K")


def test_mock_ignores_model_and_resolution():
    assert (MockProvider.model, MockProvider.resolution) == (None, None)


def test_elevenlabs_missing_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ELEVENLABS_API_KEY is not set"):
        ElevenLabsProvider()


@pytest.mark.parametrize("status, code, match", [
    (401, "invalid_api_key", "key rejected"),
    (402, "paid_plan_required", "Pro plan"),
    (403, "insufficient_permissions", "Flows permission"),
    (429, "rate_limit_exceeded", "rate limited"),
])
def test_elevenlabs_http_errors(status, code, match):
    body = {"detail": {"code": code, "message": "nope", "status": code}}
    raises_safely(eleven(lambda req: httpx.Response(status, json=body)), rf"{status} \[{code}\].*{match}")


def test_elevenlabs_generation_failed():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"id": "gen1", "status": "pending"})
        return httpx.Response(200, json={"id": "gen1", "status": "failed",
                                         "failure_reason": "moderated", "error_message": "blocked"})
    raises_safely(eleven(handler), r"failed \(moderated\): blocked")


def test_elevenlabs_poll_timeout():
    polls = []

    def handler(req):
        polls.append(req.method)
        return httpx.Response(200, json={"id": "gen1", "status": "pending"})
    raises_safely(eleven(handler, poll_interval=2.0, timeout=6.0), "not done after 6s")
    assert polls.count("GET") == 3


@pytest.mark.parametrize("exc, match", [
    (httpx.ConnectError, "network error"), (httpx.ReadTimeout, "timed out")])
def test_elevenlabs_transport_errors(exc, match):
    def handler(req):
        raise exc("boom", request=req)
    raises_safely(eleven(handler), match)
