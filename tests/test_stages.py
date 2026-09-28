import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from pipeline.models import CreativeResult, Manifest
from pipeline.stages import (
    SIZES, _fit_text, check_brand, check_copy, creative_path, fit_to_ratio, get_hero,
    load_inputs, render_creative, save_run,
)

EXAMPLES = Path(__file__).parent.parent / "examples"


class StubProvider:
    name = "stub"

    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return Image.new("RGB", (8, 8), "black")


@pytest.fixture
def inputs():
    return load_inputs(EXAMPLES / "brief.json", EXAMPLES / "brand.json")


def write_json(path, data):
    path.write_text(json.dumps(data))
    return path


def test_load_resolves_logo_to_absolute_path(inputs):
    _, brand = inputs
    logo = Path(brand.logo)
    assert logo.is_absolute() and logo.is_file()


def test_load_missing_logo_raises(tmp_path):
    brand = json.loads((EXAMPLES / "brand.json").read_text())
    brand_path = write_json(tmp_path / "brand.json", brand)
    with pytest.raises(FileNotFoundError, match="logo"):
        load_inputs(EXAMPLES / "brief.json", brand_path)


def test_load_invalid_brief_raises(tmp_path):
    brief = json.loads((EXAMPLES / "brief.json").read_text())
    brief["products"].pop()
    with pytest.raises(ValidationError):
        load_inputs(write_json(tmp_path / "brief.json", brief), EXAMPLES / "brand.json")


def test_check_copy_clean_examples(inputs):
    assert check_copy(*inputs) == []


def test_check_copy_any_locale_case_insensitive(inputs):
    brief, brand = inputs
    brief.message["es-MX"] = "Envío FREE hoy"
    assert check_copy(brief, brand) == ["free"]


def test_check_copy_whole_word_only(inputs):
    brief, brand = inputs
    brief.message["en"] = "Taste freedom"
    assert check_copy(brief, brand) == []


@pytest.mark.parametrize("ext", [".png", ".jpg"])
def test_get_hero_reuses_existing_asset(inputs, tmp_path, ext):
    brief, _ = inputs
    product = brief.products[0]
    Image.new("RGB", (8, 8), "red").save(tmp_path / f"{product.id}{ext}")
    provider = StubProvider()
    img, source = get_hero(product, brief, tmp_path, provider)
    assert source == "reused" and img.mode == "RGB"
    assert provider.prompts == []


def test_get_hero_generates_when_missing(inputs, tmp_path):
    brief, _ = inputs
    product = brief.products[0]
    provider = StubProvider()
    _, source = get_hero(product, brief, tmp_path, provider)
    assert source == "generated"
    [prompt] = provider.prompts
    for part in (product.description, brief.audience, brief.market, "centered", "no words"):
        assert part in prompt


@pytest.mark.parametrize("ratio", ["1:1", "9:16", "16:9"])
@pytest.mark.parametrize("hero_size", [(1024, 1024), (1600, 900), (500, 1400)])
def test_fit_to_ratio_exact_size(ratio, hero_size):
    assert fit_to_ratio(Image.new("RGB", hero_size), ratio).size == SIZES[ratio]


@pytest.mark.parametrize("hero_size", [(1024, 1024), (500, 1400)])
def test_fit_to_ratio_16x9_shows_whole_hero(hero_size):
    w, h = hero_size
    band = round(min(w, h) * 0.05)
    hero = Image.new("RGB", hero_size, "red")
    ImageDraw.Draw(hero).rectangle((band, band, w - band - 1, h - band - 1), fill="black")
    out = fit_to_ratio(hero, "16:9")
    scale = min(1920 / w, 1080 / h)
    fw, fh = round(w * scale), round(h * scale)
    x0, y0, inset = (1920 - fw) // 2, (1080 - fh) // 2, max(2, round(band * scale) // 2)
    edges = [(x0 + fw // 2, y0 + inset), (x0 + fw // 2, y0 + fh - 1 - inset),
             (x0 + inset, y0 + fh // 2), (x0 + fw - 1 - inset, y0 + fh // 2)]
    for xy in edges:  # every frame edge survives: nothing was cropped
        r, g, b = out.getpixel(xy)
        assert r > 200 and g < 50 and b < 50, xy


def test_fit_text_long_message_fits_two_lines():
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1080)))
    text = "An extremely long campaign message that would never fit on one line " * 3
    font, lines = _fit_text(draw, text, 972, 86)
    assert 1 <= len(lines) <= 2
    assert all(draw.textlength(ln, font=font) <= 972 for ln in lines)


@pytest.mark.parametrize("ratio", ["1:1", "9:16", "16:9"])
def test_render_creative_keeps_size_and_input(inputs, ratio):
    _, brand = inputs
    img = fit_to_ratio(Image.new("RGB", (1024, 1024), "black"), ratio)
    before = img.tobytes()
    out = render_creative(img, "Taste the summer", brand)
    assert out.size == SIZES[ratio] and out.mode == "RGB"
    assert img.tobytes() == before


@pytest.mark.parametrize("ratio", ["1:1", "9:16", "16:9"])
@pytest.mark.parametrize("message", ["Prove o verão", "Goûtez l'été", "Schmeck den Sommer ü"])
def test_render_creative_accented_text(inputs, ratio, message):
    _, brand = inputs
    img = fit_to_ratio(Image.new("RGB", (1024, 1024), "black"), ratio)
    assert render_creative(img, message, brand).size == SIZES[ratio]


def test_check_brand_detects_logo_on_rendered(inputs):
    _, brand = inputs
    img = fit_to_ratio(Image.new("RGB", (1024, 1024), "black"), "9:16")
    assert check_brand(render_creative(img, "Hola", brand), brand).logo_present
    assert not check_brand(img, brand).logo_present


def test_check_brand_color_share(inputs):
    _, brand = inputs
    assert check_brand(Image.new("RGB", (100, 100), brand.colors[0]), brand).brand_color_share == 1.0
    assert check_brand(Image.new("RGB", (100, 100), "black"), brand).brand_color_share == 0.0


def test_check_brand_never_raises(inputs):
    _, brand = inputs
    broken = brand.model_copy(update={"logo": "/does/not/exist.png"})
    checks = check_brand(Image.new("RGBA", (3, 3)), broken)
    assert checks.logo_present is False and checks.prohibited_words == []


def test_save_run_writes_creatives_and_manifest(inputs, tmp_path):
    _, brand = inputs
    checks = check_brand(Image.new("RGB", (8, 8)), brand)
    result = CreativeResult(
        product_id="citrus-soda", ratio="9:16", path=creative_path("citrus-soda", "es-MX", "9:16"),
        source="generated", locale="es-MX", checks=checks,
    )
    manifest = save_run([(result, Image.new("RGB", (8, 8)))], "fizz", "mock", tmp_path)
    assert (tmp_path / "citrus-soda" / "es-MX" / "9x16" / "creative.png").is_file()
    assert Manifest.model_validate_json((tmp_path / "manifest.json").read_text()) == manifest
