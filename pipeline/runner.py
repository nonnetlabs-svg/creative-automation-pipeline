"""Wires the stages in the order of docs/stages.md "Flow"."""
from pathlib import Path

from PIL import Image

from pipeline.models import CreativeResult, Hero, Manifest
from pipeline.providers import ImageProvider
from pipeline.stages import (
    check_brand, check_copy, creative_path, fit_to_ratio, get_hero, load_inputs,
    render_creative, save_run,
)


class BlockedCopyError(ValueError):
    def __init__(self, words: list[str]):
        self.words = words
        super().__init__(
            f"Brief copy uses prohibited words: {', '.join(words)}. No images generated."
        )


def run_pipeline(
    brief_path: Path, brand_path: Path, assets_dir: Path, out_dir: Path, provider: ImageProvider
) -> Manifest:
    brief, brand = load_inputs(brief_path, brand_path)
    # Stop before any provider call or file write: a blocked run costs $0.
    hits = check_copy(brief, brand)
    if hits:
        raise BlockedCopyError(hits)

    creatives: list[tuple[CreativeResult, Image.Image]] = []
    heroes: list[Hero] = []
    for product in brief.products:
        hero_img, hero = get_hero(product, brief, assets_dir, provider)  # once per product
        heroes.append(hero)
        for locale in brief.locales:
            message = brief.message[locale]  # Brief guarantees the key; no fallback
            for ratio in brief.aspect_ratios:
                img = render_creative(fit_to_ratio(hero_img, ratio), message, brand)
                result = CreativeResult(
                    product_id=product.id, ratio=ratio,
                    path=creative_path(product.id, locale, ratio),
                    source=hero.source, locale=locale, checks=check_brand(img, brand),
                )
                creatives.append((result, img))
    return save_run(creatives, heroes, brief.campaign_id, provider.name,
                    out_dir / brief.campaign_id)
