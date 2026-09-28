import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from pipeline.models import BrandRules, Brief, Hero

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


def test_reused_hero_rejects_generation_fields():
    # Reused heroes carry source only; a hand-added prompt must fail, not vanish.
    with pytest.raises(ValidationError, match="prompt"):
        TypeAdapter(Hero).validate_python(
            {"product_id": "citrus-soda", "source": "reused", "prompt": "lime soda"})


def test_rejects_single_product(brief):
    brief["products"].pop()
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_unknown_ratio(brief):
    brief["aspect_ratios"].append("4:3")
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_duplicate_ratio(brief):
    brief["aspect_ratios"].append("1:1")
    with pytest.raises(ValidationError, match="duplicates"):
        Brief.model_validate(brief)


def test_rejects_message_without_en(brief):
    del brief["message"]["en"]
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_locale_missing_from_message(brief):
    brief["locales"].append("it-IT")
    with pytest.raises(ValidationError, match="it-IT"):
        Brief.model_validate(brief)


def test_rejects_duplicate_locale(brief):
    brief["locales"].append("en")
    with pytest.raises(ValidationError, match="duplicates"):
        Brief.model_validate(brief)


def test_rejects_empty_locales(brief):
    brief["locales"] = []
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


@pytest.mark.parametrize("bad", ["es_mx", "../x", "ES-mx", "en-"])
def test_rejects_bad_locale_format(brief, bad):
    brief["locales"] = [bad]
    brief["message"][bad] = "x"
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_unsupported_language(brief):
    brief["locales"].append("ja-JP")
    brief["message"]["ja-JP"] = "夏を味わおう"
    with pytest.raises(ValidationError, match=r"not supported yet: \['ja-JP'\]"):
        Brief.model_validate(brief)


@pytest.mark.parametrize("bad", ["Citrus-Soda", "../x", "citrus_soda", "-citrus", "a--b"])
def test_rejects_bad_product_id(brief, bad):
    brief["products"][0]["id"] = bad
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_path_like_campaign_id(brief):
    brief["campaign_id"] = "../x"
    with pytest.raises(ValidationError):
        Brief.model_validate(brief)


def test_rejects_old_schema_version(brief):
    brief["schema_version"] = "1.0"
    with pytest.raises(ValidationError, match="unsupported schema_version '1.0'"):
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
