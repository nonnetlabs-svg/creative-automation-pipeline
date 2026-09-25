"""Pipeline stages from docs/stages.md."""
import re
from pathlib import Path

from PIL import Image

from pipeline.models import BrandRules, Brief, Product, Source
from pipeline.providers import ImageProvider

HERO_EXTENSIONS = (".png", ".jpg")


def load_inputs(brief_path: Path, brand_path: Path) -> tuple[Brief, BrandRules]:
    brief = Brief.model_validate_json(brief_path.read_text())
    brand = BrandRules.model_validate_json(brand_path.read_text())
    # Resolve once here so later stages never need to know where brand.json was.
    logo = (brand_path.parent / brand.logo).resolve()
    if not logo.is_file():
        raise FileNotFoundError(f"Brand logo not found: {logo} (from {brand_path})")
    return brief, brand.model_copy(update={"logo": str(logo)})


def check_copy(brief: Brief, brand: BrandRules) -> list[str]:
    found = []
    for word in brand.prohibited_words:
        pattern = rf"\b{re.escape(word)}\b"
        if word not in found and any(
            re.search(pattern, text, re.IGNORECASE) for text in brief.message.values()
        ):
            found.append(word)
    return found


def _hero_prompt(product: Product, brief: Brief) -> str:
    return (
        f"Product photo of {product.description}, "
        f"for {brief.audience} in {brief.market}. Clean background, no text."
    )


def get_hero(
    product: Product, brief: Brief, assets_dir: Path, provider: ImageProvider
) -> tuple[Image.Image, Source]:
    for ext in HERO_EXTENSIONS:
        path = assets_dir / f"{product.id}{ext}"
        if path.is_file():
            with Image.open(path) as img:
                return img.convert("RGB"), "reused"
    return provider.generate(_hero_prompt(product, brief)), "generated"
