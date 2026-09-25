import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.models import BrandRules, Brief

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture
def brief():
    return json.loads((EXAMPLES / "brief.json").read_text())


@pytest.fixture
def brand():
    return json.loads((EXAMPLES / "brand.json").read_text())


def test_examples_are_valid(brief, brand):
    Brief.model_validate(brief)
    BrandRules.model_validate(brand)


def test_rejects_single_product(brief):
    brief["products"].pop()
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_unknown_ratio(brief):
    brief["aspect_ratios"].append("4:3")
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_message_without_en(brief):
    del brief["message"]["en"]
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_non_hex_color(brand):
    brand["colors"].append("green")
    with pytest.raises(ValidationError):
        BrandRules.model_validate(brand)


def test_brief_rejects_unknown_key(brief):
    brief["extra"] = 1
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_brand_rejects_unknown_key(brand):
    brand["prohibited_word"] = []
    with pytest.raises(ValidationError):
        BrandRules.model_validate(brand)


def test_product_rejects_unknown_key(brief):
    brief["products"][0]["descripton"] = "x"
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)
