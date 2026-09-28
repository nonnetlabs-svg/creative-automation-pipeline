"""Pipeline stages from docs/stages.md."""
import logging
import re
import string
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageStat

from pipeline.models import (
    BrandChecks, BrandRules, Brief, CreativeResult, GeneratedHero, Hero, Manifest, Product, Ratio,
    ReusedHero,
)
from pipeline.providers import ImageProvider

Box = tuple[int, int, int, int]  # (x0, y0, x1, y1), pixels
HERO_EXTENSIONS = (".png", ".jpg")
HERO_DIR = "heroes"  # generated heroes land in <run_dir>/heroes/<product-id>.png
SQUARE_TOLERANCE = 0.01  # max |w - h| for a hero, as a share of its short side
SIZES = {"1:1": (1080, 1080), "9:16": (1080, 1920), "16:9": (1920, 1080)}
# Prompt COMPOSITION puts the can top at ~20% and plinth base at ~70% of the hero: center 45%.
HERO_SUBJECT_Y = 0.45
# Frame row for that center (9:16: subject lands at ~32-60%, inside the spec's 30-62%) and
# frame column for the hero's center (16:9: 62% per spec). Clamping makes 1:1 and 16:9 rows moot.
SUBJECT_Y: dict[Ratio, float] = {"1:1": 0.5, "9:16": 0.46, "16:9": 0.5}
CENTER_X: dict[Ratio, float] = {"1:1": 0.5, "9:16": 0.5, "16:9": 0.62}
PAD_STRIP = 16  # px of hero edge averaged into each pad
SAMPLE_ROWS = 0.05  # top/bottom share of hero sampled for wall/floor color
SUBJECT_TOLERANCE = 40  # max channel diff from both wall and floor to count as subject
GAP_SHARE = 0.04  # min lockup-subject gap, of the short edge (spec B2)
MIN_TYPE = 18  # px; below this the tagline "can't fit" (fallback band is deferred)
COARSE_STEP = 8  # px per step in the lockup size search, before 1px refinement
WORDMARK_SHARE = 0.6  # wordmark width / tagline block width
WORDMARK_GAP = 0.25  # wordmark-to-tagline gap, of tagline size
LEADING = 1.0  # tagline baseline-to-baseline, of tagline size
CONTRAST_MIN = 4.5  # WCAG AA; below this the lockup switches to the cream fallback
COLOR_TOLERANCE = 40  # RGB distance to count as "brand color"

log = logging.getLogger(__name__)


def load_inputs(brief_path: Path, brand_path: Path) -> tuple[Brief, BrandRules]:
    brief = Brief.model_validate_json(brief_path.read_text())
    brand = BrandRules.model_validate_json(brand_path.read_text())
    # Resolve once here so later stages never need to know where brand.json was.
    font = (brand_path.parent / brand.font).resolve()
    if not font.is_file():
        raise FileNotFoundError(f"Brand font not found: {font} (from {brand_path})")
    # Cross-file rules: each model only sees its own file, so they live here.
    palette = {c.upper() for c in brand.colors}
    placeholders = {f for _, f, _, _ in string.Formatter().parse(brand.hero_prompt_template) if f}
    for p in brief.products:
        if p.deep_color.upper() not in palette:
            raise ValueError(f"{p.id}: deep_color {p.deep_color} is not in the brand palette")
        missing, extra = placeholders - p.prompt_vars.keys(), p.prompt_vars.keys() - placeholders
        if missing or extra:
            raise ValueError(f"{p.id}: prompt_vars missing {sorted(missing)}, extra {sorted(extra)}")
    # Zones are fixed and the font is known, so a tagline that can't fit fails here, at $0.
    for loc in brief.locales:
        for ratio in brief.aspect_ratios:
            try:
                _set_lockup(*lockup_zone(ratio, SIZES[ratio]), brief.message[loc], str(font),
                            brand.wordmark)
            except ValueError as err:
                raise ValueError(f"{loc} {ratio}: {err}") from None
    return brief, brand.model_copy(update={"font": str(font)})


def check_copy(brief: Brief, brand: BrandRules) -> list[str]:
    found = []
    for word in brand.prohibited_words:
        pattern = rf"\b{re.escape(word)}\b"
        if word not in found and any(
            re.search(pattern, text, re.IGNORECASE) for text in brief.message.values()
        ):
            found.append(word)
    return found


def _hero_prompt(product: Product, brand: BrandRules) -> str:
    # AVOID stays inside the template: the API has no negative-prompt field.
    return brand.hero_prompt_template.format(**product.prompt_vars)


def _require_square(img: Image.Image, what: str) -> Image.Image:
    # Placement and lockup zones assume a 1:1 hero; anything else would put type on the can.
    w, h = img.size
    if abs(w - h) > SQUARE_TOLERANCE * min(w, h):  # not w/h - 1: float error rejects exactly 1%
        raise ValueError(f"{what} is {w}x{h}; heroes must be 1:1 (within 1%)")
    return img


def get_hero(
    product: Product, brand: BrandRules, assets_dir: Path, provider: ImageProvider, run_dir: Path
) -> tuple[Image.Image, Hero]:
    for ext in HERO_EXTENSIONS:
        path = assets_dir / f"{product.id}{ext}"
        if path.is_file():  # reused: assets/products/ is the record, nothing is copied
            with Image.open(path) as img:
                return _require_square(img.convert("RGB"), f"Hero {path}"), ReusedHero(
                    product_id=product.id)
    prompt = _hero_prompt(product, brand)  # built once: the manifest records exactly what was sent
    img = provider.generate(prompt)
    # Saved before any check or render: a paid hero survives even if the run fails after this.
    rel = f"{HERO_DIR}/{product.id}.png"
    (run_dir / HERO_DIR).mkdir(parents=True, exist_ok=True)
    img.save(run_dir / rel)
    hero = GeneratedHero(product_id=product.id, model=provider.model,
                         resolution=provider.resolution, prompt=prompt, path=rel)
    return _require_square(img, f"Generated hero for {product.id}"), hero


def _placement(hero_size: tuple[int, int], ratio: Ratio) -> tuple[float, int, int]:
    """Scale and top-left offset of the hero in the frame; shared by the fit and the subject box."""
    (W, H), (w, h) = SIZES[ratio], hero_size
    scale = min(W / w, H / h)  # contain: the hero is never cropped
    fw, fh = round(w * scale), round(h * scale)
    x = min(max(round(W * CENTER_X[ratio] - fw / 2), 0), W - fw)
    y = min(max(round(H * SUBJECT_Y[ratio] - fh * HERO_SUBJECT_Y), 0), H - fh)
    return scale, x, y


def _pad_vertical(img: Image.Image, top: int, bottom: int) -> Image.Image:
    # Average the edge strip into one row and stretch it: wall extends up, floor extends down.
    w, h = img.size
    s = min(PAD_STRIP, h)
    out = Image.new("RGB", (w, h + top + bottom))
    out.paste(img, (0, top))
    for box, height, y in (((0, 0, w, s), top, 0), ((0, h - s, w, h), bottom, top + h)):
        if height:
            row = img.crop(box).resize((w, 1), Image.BOX)
            out.paste(row.resize((w, height), Image.NEAREST), (0, y))
    return out


def fit_to_ratio(hero: Image.Image, ratio: Ratio) -> Image.Image:
    (W, H) = SIZES[ratio]
    scale, x, y = _placement(hero.size, ratio)
    img = hero.convert("RGB").resize(
        (round(hero.width * scale), round(hero.height * scale)), Image.LANCZOS)
    img = _pad_vertical(img, y, H - y - img.height)
    t = Image.Transpose.TRANSPOSE  # sides reuse the vertical pad; each row keeps wall/floor split
    return _pad_vertical(img.transpose(t), x, W - x - img.width).transpose(t)


def subject_box(hero: Image.Image) -> Box | None:
    """Box of pixels unlike both the wall (top rows) and floor (bottom rows); None if none."""
    small = hero.convert("RGB")
    small.thumbnail((256, 256))
    w, h = small.size
    n = max(1, round(h * SAMPLE_ROWS))
    masks = []
    for rows in ((0, 0, w, n), (0, h - n, w, h)):
        color = tuple(ImageStat.Stat(small.crop(rows)).median)
        r, g, b = ImageChops.difference(small, Image.new("RGB", small.size, color)).split()
        far = ImageChops.lighter(ImageChops.lighter(r, g), b)  # max channel difference
        masks.append(far.point(lambda v: 255 if v > SUBJECT_TOLERANCE else 0))
    box = ImageChops.darker(*masks).filter(ImageFilter.MedianFilter(5)).getbbox()
    if box is None:
        return None
    k = hero.width / w
    return tuple(round(v * k) for v in box)


def map_box(box: Box, hero_size: tuple[int, int], ratio: Ratio) -> Box:
    """Hero-space box -> creative-space box, using the same placement as fit_to_ratio."""
    scale, x, y = _placement(hero_size, ratio)
    x0, y0, x1, y1 = box
    return (x + round(x0 * scale), y + round(y0 * scale),
            x + round(x1 * scale), y + round(y1 * scale))


def lockup_zone(ratio: Ratio, size: tuple[int, int]) -> tuple[Box, str, str]:
    """Fixed zone + (h, v) alignment per ratio from spec B2. Subject-aware placement replaces this."""
    W, H = size
    gap = GAP_SHARE * min(W, H)
    if ratio == "9:16":  # safe zone (top 14%, left 6%, right 15%), centered on the can's axis,
        box, align = (0.15 * W, 0.14 * H, 0.85 * W, 0.30 * H - gap), ("center", "middle")  # above subject
    elif ratio == "16:9":  # left margin 8%, stops a gap short of the hero's center half
        box, align = (0.08 * W, 0.10 * H, 0.62 * W - H / 4 - gap, 0.90 * H), ("left", "middle")
    else:  # 1:1: floor zone a gap below the plinth base (~70%), 6% bottom margin
        box, align = (0.08 * W, 0.70 * H + gap, 0.92 * W, 0.94 * H), ("center", "bottom")
    return tuple(round(v) for v in box), *align


@lru_cache(maxsize=None)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _layout_at(size: int, zone: Box, h_align: str, v_align: str, message: str, font_path: str,
               wordmark: str) -> tuple[list, Box] | None:
    """Wordmark over <=2 balanced tagline lines at one tagline size; None if it overflows."""
    x0, y0, x1, y1 = zone
    words = message.split()
    splits = [[" ".join(words[:i]), " ".join(words[i:])] for i in range(1, len(words))]
    font = _font(font_path, size)
    width = lambda lines: max(font.getlength(ln) for ln in lines)  # noqa: E731
    lines = [message] if font.getlength(message) <= x1 - x0 else min(splits, key=width, default=[message])
    block_w = width(lines)
    wm = _font(font_path, max(1, round(size * WORDMARK_SHARE * block_w / font.getlength(wordmark))))
    wm_h = -wm.getbbox(wordmark, anchor="ls")[1]
    ascent = -min(font.getbbox(ln, anchor="ls")[1] for ln in lines)  # includes accents
    descent = font.getbbox(lines[-1], anchor="ls")[3]
    gap, lead = round(size * WORDMARK_GAP), round(size * LEADING)
    block_h = wm_h + gap + ascent + lead * (len(lines) - 1) + descent
    if block_w > x1 - x0 or block_h > y1 - y0:
        return None
    top = y1 - block_h if v_align == "bottom" else (y0 + y1 - block_h) // 2
    x, anchor = (x0, "ls") if h_align == "left" else ((x0 + x1) // 2, "ms")
    ops = [((x, top + wm_h), wordmark, wm, anchor)]
    ops += [((x, top + wm_h + gap + ascent + i * lead), ln, font, anchor) for i, ln in enumerate(lines)]
    inks = [(ox + l, oy + t, ox + r, oy + b)
            for (ox, oy), text, f, a in ops for l, t, r, b in [f.getbbox(text, anchor=a)]]
    return ops, tuple(agg(v[i] for v in inks) for i, agg in enumerate((min, min, max, max)))


def _set_lockup(zone: Box, h_align: str, v_align: str, message: str, font_path: str,
                wordmark: str) -> tuple[list, Box]:
    """Largest tagline size that fits the zone. Layout only, no pixels; raises below MIN_TYPE."""
    layout = lambda s: _layout_at(s, zone, h_align, v_align, message, font_path, wordmark)  # noqa: E731
    start = max(min(zone[2] - zone[0], zone[3] - zone[1]) // 2, MIN_TYPE)
    # Coarse steps down, then 1px refinement up: ~6x fewer layouts than stepping 1px from the top.
    sizes = [*range(start, MIN_TYPE, -COARSE_STEP), MIN_TYPE]
    size, result = next(((s, r) for s in sizes if (r := layout(s))), (None, None))
    if result is None:
        raise ValueError(f"tagline {message!r} does not fit the lockup zone at >= {MIN_TYPE}px")
    while size < start and (r := layout(size + 1)):
        size, result = size + 1, r
    return result


def _luminance(rgb: tuple[int, ...]) -> float:
    # WCAG 2.x relative luminance (sRGB linearized).
    c = [s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4 for s in (v / 255 for v in rgb[:3])]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(color: str, region: Image.Image) -> float:
    """WCAG ratio vs. the region: worst of its 5th/95th luminance percentiles (ignores specks)."""
    small = region.convert("RGB")
    small.thumbnail((64, 64))
    lums = sorted(_luminance(p) for p in small.get_flattened_data())
    text = _luminance(ImageColor.getrgb(color))
    ratio = lambda bg: (max(text, bg) + 0.05) / (min(text, bg) + 0.05)  # noqa: E731
    return min(ratio(lums[int(0.05 * (len(lums) - 1))]), ratio(lums[int(0.95 * (len(lums) - 1))]))


class Lockup(NamedTuple):
    box: Box
    color: str
    contrast: float


def render_creative(img: Image.Image, message: str, brand: BrandRules, deep_color: str,
                    ratio: Ratio) -> tuple[Image.Image, Lockup]:
    out = img.convert("RGB")  # always a copy; caller's image is untouched
    # load_inputs already proved the fit; a raise here is a safety assert, not a normal path.
    ops, box = _set_lockup(*lockup_zone(ratio, out.size), message, brand.font, brand.wordmark)
    behind = out.crop(box)  # measured before drawing: the pixels the type will sit on
    color, contrast = deep_color, _contrast(deep_color, behind)
    if contrast < CONTRAST_MIN:  # cream may also fail: reported, not fixed (fallback band deferred)
        color, contrast = brand.text_fallback_color, _contrast(brand.text_fallback_color, behind)
    draw = ImageDraw.Draw(out)
    for xy, text, font, anchor in ops:
        draw.text(xy, text, font=font, fill=color, anchor=anchor)
    return out, Lockup(box, color, round(contrast, 2))


def _color_share(img: Image.Image, colors: list[str]) -> float:
    targets = [ImageColor.getrgb(c) for c in colors]
    pixels = img.convert("RGB").resize((64, 64)).get_flattened_data()
    near = sum(
        any(sum((p - t) ** 2 for p, t in zip(px, tgt)) <= COLOR_TOLERANCE**2 for tgt in targets)
        for px in pixels
    )
    return near / len(pixels)


def check_brand(img: Image.Image, brand: BrandRules, lockup: Lockup,
                subject: Box | None) -> BrandChecks:
    # Report only: a failed check is a finding, never a crash.
    try:
        share = _color_share(img, brand.colors)
    except Exception:
        log.warning("color check failed", exc_info=True)
        share = 0.0
    overlaps = None  # no subject detected: unknown, not "clear"
    if subject is not None:
        g, (a, b) = GAP_SHARE * min(img.size), (lockup.box, subject)
        overlaps = a[0] - g < b[2] and b[0] < a[2] + g and a[1] - g < b[3] and b[1] < a[3] + g
    # Copy is checked up front by check_copy, which stops the run on any hit.
    return BrandChecks(lockup_contrast=lockup.contrast, lockup_color=lockup.color,
                       overlaps_subject=overlaps, brand_color_share=share, prohibited_words=[])


def creative_path(product_id: str, locale: str, ratio: Ratio) -> str:
    r = ratio.replace(":", "x")
    return f"{product_id}/{locale}/{r}/{product_id}_{r}_{locale}.png"


def save_run(
    creatives: list[tuple[CreativeResult, Image.Image]], heroes: list[Hero], campaign_id: str,
    provider: str, out_dir: Path,
) -> Manifest:
    for result, img in creatives:
        path = out_dir / result.path
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
    manifest = Manifest(
        campaign_id=campaign_id, provider=provider, status="ok", heroes=heroes,
        creatives=[r for r, _ in creatives],
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    return manifest
