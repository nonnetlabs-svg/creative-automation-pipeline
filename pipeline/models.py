"""Data shapes from docs/data-shapes.md."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Ratio = Literal["1:1", "9:16", "16:9"]
Hex = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    campaign_id: str
    market: str
    locale: str
    audience: str
    message: dict[str, str]
    aspect_ratios: list[Ratio] = Field(min_length=1)
    products: list[Product] = Field(min_length=2)

    @field_validator("message")
    @classmethod
    def require_english(cls, v: dict[str, str]) -> dict[str, str]:
        if "en" not in v:
            raise ValueError('message must include "en"')
        return v


class BrandRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colors: list[Hex] = Field(min_length=1)
    logo: str
    prohibited_words: list[str]


class BrandChecks(BaseModel):
    logo_present: bool
    brand_color_share: float = Field(ge=0, le=1)
    prohibited_words: list[str]


class CreativeResult(BaseModel):
    product_id: str
    ratio: Ratio
    path: str
    source: Literal["reused", "generated"]
    locale: str
    checks: BrandChecks


class Manifest(BaseModel):
    campaign_id: str
    provider: str
    status: str
    creatives: list[CreativeResult]
