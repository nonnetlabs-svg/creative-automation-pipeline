"""Image providers: the plug-in slot from docs/stages.md."""
import hashlib
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont

SIZE = (1024, 1024)
FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Inter-Bold.ttf"
FONT = ImageFont.truetype(str(FONT_PATH), 48)


class ImageProvider(Protocol):
    name: str

    def generate(self, prompt: str) -> Image.Image: ...


class MockProvider:
    """Deterministic, offline stand-in: same prompt -> same pixels."""

    name = "mock"

    def generate(self, prompt: str) -> Image.Image:
        # hashlib, not hash(): hash() is salted per process.
        r, g, b = hashlib.sha256(prompt.encode("utf-8")).digest()[:3]
        img = Image.new("RGB", SIZE, (r, g, b))
        ImageDraw.Draw(img).text((40, 40), prompt[:40], font=FONT, fill="white")
        return img
