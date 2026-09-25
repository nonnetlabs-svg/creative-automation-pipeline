import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from pipeline.stages import check_copy, get_hero, load_inputs

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
    for part in (product.description, brief.audience, brief.market, "no text"):
        assert part in prompt
