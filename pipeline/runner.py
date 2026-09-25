"""Wires the stages in the order of docs/stages.md "Flow"."""
from pathlib import Path

from PIL import Image

from pipeline.models import CreativeResult, Manifest
from pipeline.providers import ImageProvider
from pipeline.stages import (
    check_brand, check_copy, creative_path, fit_to_ratio, get_hero, load_inputs,
    pick_message, render_creative, save_run,
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

    message, locale = pick_message(brief)
    creatives: list[tuple[CreativeResult, Image.Image]] = []
    for product in brief.products:
        hero, source = get_hero(product, brief, assets_dir, provider)  # once per product
        for ratio in brief.aspect_ratios:
            img = render_creative(fit_to_ratio(hero, ratio), message, brand)
            result = CreativeResult(
                product_id=product.id, ratio=ratio, path=creative_path(product.id, ratio),
                source=source, locale=locale, checks=check_brand(img, brand),
            )
            creatives.append((result, img))
    return save_run(creatives, brief.campaign_id, provider.name, out_dir / brief.campaign_id)
