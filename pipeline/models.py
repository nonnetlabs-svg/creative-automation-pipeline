"""Data shapes from docs/data-shapes.md."""
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator,
)

from pipeline.providers import MODELS

Ratio = Literal["1:1", "9:16", "16:9"]
Source = Literal["reused", "generated"]
Hex = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
# Both become folder names in creative paths, so no "/", "..", or case drift.
Locale = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
# Latin-script languages Inter + space-based wrapping handle; see docs/stages.md.
SUPPORTED_LANGUAGES = frozenset({"en", "es", "pt", "fr", "de", "it", "nl"})


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Slug
    name: str
    description: str
    deep_color: Hex  # lockup color; must be in the brand palette (checked in load_inputs)
    prompt_vars: dict[str, str]  # keys must match the brand template's placeholders


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    campaign_id: Slug
    market: str
    locales: list[Locale] = Field(min_length=1)
    audience: str
    message: dict[str, str]
    aspect_ratios: list[Ratio] = Field(min_length=1)
    products: list[Product] = Field(min_length=2)

    @field_validator("schema_version", mode="before")
    @classmethod
    def supported_version(cls, v: object) -> object:
        # Runs before the Literal check so an old brief gets a readable reason.
        if v != "1.1":
            raise ValueError(f"unsupported schema_version {v!r}; expected '1.1'")
        return v

    @field_validator("message")
    @classmethod
    def require_english(cls, v: dict[str, str]) -> dict[str, str]:
        if "en" not in v:
            raise ValueError('message must include "en"')
        return v

    @field_validator("message")
    @classmethod
    def typographic_punctuation(cls, v: dict[str, str]) -> dict[str, str]:
        # Spec: validated before render, so a straight quote never reaches the lockup.
        bad = [loc for loc, text in v.items() if "'" in text or '"' in text]
        if bad:
            raise ValueError(f"message uses ASCII quotes in {bad}; use ’ “ ” instead")
        return v

    @field_validator("aspect_ratios")
    @classmethod
    def no_duplicate_ratios(cls, v: list[Ratio]) -> list[Ratio]:
        dupes = sorted({r for r in v if v.count(r) > 1})
        if dupes:
            raise ValueError(f"aspect_ratios has duplicates: {dupes}")
        return v

    @field_validator("locales")
    @classmethod
    def no_duplicate_locales(cls, v: list[str]) -> list[str]:
        dupes = sorted({loc for loc in v if v.count(loc) > 1})
        if dupes:
            raise ValueError(f"locales has duplicates: {dupes}")
        return v

    @field_validator("locales")
    @classmethod
    def supported_languages(cls, v: list[str]) -> list[str]:
        # Fail at load rather than render tofu boxes or reversed text.
        bad = [loc for loc in v if loc.split("-")[0] not in SUPPORTED_LANGUAGES]
        if bad:
            raise ValueError(
                f"locales not supported yet: {bad}; see docs/stages.md (CJK and RTL)"
            )
        return v

    @model_validator(mode="after")
    def locales_have_message(self) -> "Brief":
        # No fallback: a locale without copy is a broken brief, not an English creative.
        missing = [loc for loc in self.locales if loc not in self.message]
        if missing:
            raise ValueError(f"locales missing from message: {missing}")
        return self


class BrandRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colors: list[Hex] = Field(min_length=1)
    text_fallback_color: Hex
    wordmark: str
    font: str  # resolved relative to brand.json by load_inputs
    hero_prompt_template: str
    hero_model: str  # one model per run; the CLI's --model overrides it
    prohibited_words: list[str]

    @field_validator("hero_model")
    @classmethod
    def known_model(cls, v: str) -> str:
        # At load, so a typo in brand.json costs $0, same as a bad --model.
        if v not in MODELS:
            raise ValueError(f"unknown hero_model {v!r}; choose from {', '.join(MODELS)}")
        return v


class BrandChecks(BaseModel):
    lockup_contrast: float  # WCAG ratio of lockup_color vs. the pixels behind the lockup
    lockup_color: Hex  # deep color; cream if deep < 4.5 and cream measures higher
    overlaps_subject: bool | None  # report only (B2-lite); None when no subject was detected
    brand_color_share: float = Field(ge=0, le=1)
    prohibited_words: list[str]


class CreativeResult(BaseModel):
    product_id: str
    ratio: Ratio
    path: str
    source: Source
    locale: str
    checks: BrandChecks


class ReusedHero(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a hand-added prompt here is an error, not ignored

    product_id: str
    source: Literal["reused"] = "reused"


class GeneratedHero(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    source: Literal["generated"] = "generated"
    model: str | None  # None when the provider ignores it (mock)
    resolution: str | None
    prompt: str  # exact text sent, so a hero can be traced back or regenerated
    path: str  # raw hero, relative to the run folder, for approval into assets/products/


# One per product. Reused heroes carry source only; the file in assets/products/ is the record.
Hero = Annotated[ReusedHero | GeneratedHero, Field(discriminator="source")]


class Manifest(BaseModel):
    campaign_id: str
    provider: str
    status: str
    heroes: list[Hero]
    creatives: list[CreativeResult]
