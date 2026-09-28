"""Pipeline stages from docs/stages.md."""
import logging
import re
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

from pipeline.models import (
    BrandChecks, BrandRules, Brief, CreativeResult, Manifest, Product, Ratio, Source,
)
from pipeline.providers import FONT_PATH, ImageProvider

HERO_EXTENSIONS = (".png", ".jpg")
SIZES = {"1:1": (1080, 1080), "9:16": (1080, 1920), "16:9": (1920, 1080)}
# crop = center cover-crop; contain = whole hero over a blurred cover-crop of itself
FIT_MODES: dict[Ratio, str] = {"1:1": "crop", "9:16": "crop", "16:9": "contain"}
BLUR_RADIUS = 40
MARGIN = 0.05  # of image width
LOGO_SHARE = 0.15  # logo width / image width
MAX_LINES = 2
LOGO_TOLERANCE = 12  # mean abs RGB diff on opaque logo pixels
COLOR_TOLERANCE = 40  # RGB distance to count as "brand color"

log = logging.getLogger(__name__)


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
        f"for {brief.audience} in {brief.market}. Product centered with generous "
        "space around it. Clean background. Blank, unbranded can label. The image "
        "itself contains no words, letters, or numbers; all copy is added later."
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


def fit_to_ratio(hero: Image.Image, ratio: Ratio) -> Image.Image:
    size = SIZES[ratio]
    cover = ImageOps.fit(hero, size, Image.LANCZOS, centering=(0.5, 0.5))
    if FIT_MODES[ratio] == "crop":
        return cover
    bg = cover.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    fg = ImageOps.contain(hero, size, Image.LANCZOS)
    bg.paste(fg, ((size[0] - fg.width) // 2, (size[1] - fg.height) // 2))
    return bg


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= max_w:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_w: int, start: int):
    for size in range(start, 0, -1):
        font = ImageFont.truetype(str(FONT_PATH), size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= MAX_LINES and all(draw.textlength(ln, font=font) <= max_w for ln in lines):
            return font, lines
    raise ValueError(f"Message cannot fit: {text!r}")


def _logo_placement(size: tuple[int, int], logo_path: str):
    w = size[0]
    with Image.open(logo_path) as src:
        logo = src.convert("RGBA")
    target_w = round(w * LOGO_SHARE)
    logo = logo.resize((target_w, max(1, round(logo.height * target_w / logo.width))), Image.LANCZOS)
    margin = round(w * MARGIN)
    return logo, (w - margin - target_w, margin)


def render_creative(img: Image.Image, message: str, brand: BrandRules) -> Image.Image:
    out = img.convert("RGB")  # always a copy; caller's image is untouched
    w, h = out.size
    margin = round(w * MARGIN)
    draw = ImageDraw.Draw(out)
    font, lines = _fit_text(draw, message, w - 2 * margin, round(min(w, h) * 0.08))
    line_h, pad = round(font.size * 1.25), margin // 2
    band_top = h - margin - (len(lines) * line_h + 2 * pad)
    draw.rectangle((0, band_top, w, h - margin), fill=brand.colors[0])
    for i, line in enumerate(lines):
        draw.text((w / 2, band_top + pad + i * line_h), line, font=font, fill="white", anchor="ma")
    logo, xy = _logo_placement(out.size, brand.logo)
    out.paste(logo, xy, mask=logo)
    return out


def _logo_matches(img: Image.Image, logo_path: str) -> bool:
    logo, (x, y) = _logo_placement(img.size, logo_path)
    region = img.convert("RGB").crop((x, y, x + logo.width, y + logo.height))
    diffs = [
        sum(abs(p - q) for p, q in zip(px, lp[:3])) / 3
        for px, lp in zip(region.get_flattened_data(), logo.get_flattened_data())
        if lp[3] > 250  # fully opaque only; soft edges blend with the background
    ]
    return bool(diffs) and sum(diffs) / len(diffs) < LOGO_TOLERANCE


def _color_share(img: Image.Image, colors: list[str]) -> float:
    targets = [ImageColor.getrgb(c) for c in colors]
    pixels = img.convert("RGB").resize((64, 64)).get_flattened_data()
    near = sum(
        any(sum((p - t) ** 2 for p, t in zip(px, tgt)) <= COLOR_TOLERANCE**2 for tgt in targets)
        for px in pixels
    )
    return near / len(pixels)


def check_brand(img: Image.Image, brand: BrandRules) -> BrandChecks:
    # Report only: a failed check is a finding, never a crash.
    try:
        logo_present = _logo_matches(img, brand.logo)
    except Exception:
        log.warning("logo check failed", exc_info=True)
        logo_present = False
    try:
        share = _color_share(img, brand.colors)
    except Exception:
        log.warning("color check failed", exc_info=True)
        share = 0.0
    # Copy is checked up front by check_copy, which stops the run on any hit.
    return BrandChecks(logo_present=logo_present, brand_color_share=share, prohibited_words=[])


def creative_path(product_id: str, locale: str, ratio: Ratio) -> str:
    return f"{product_id}/{locale}/{ratio.replace(':', 'x')}/creative.png"


def save_run(
    creatives: list[tuple[CreativeResult, Image.Image]], campaign_id: str, provider: str, out_dir: Path
) -> Manifest:
    for result, img in creatives:
        path = out_dir / result.path
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
    manifest = Manifest(
        campaign_id=campaign_id, provider=provider, status="ok", creatives=[r for r, _ in creatives]
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    return manifest
