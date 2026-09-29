import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

from pipeline.models import CreativeResult, GeneratedHero, Manifest
from pipeline.providers import MockProvider
from pipeline.stages import (
    HERO_SCALE_1x1, SIZES, TAGLINE_PX, Lockup, _set_lockup, check_brand, check_copy, creative_path, fit_to_ratio, get_hero,
    load_inputs, lockup_zone, map_box, render_creative, save_run, subject_box,
)

EXAMPLES = Path(__file__).parent.parent / "examples"
RATIOS = ["1:1", "9:16", "16:9"]
DEEP, CREAM = "#1F5E2E", "#FFF6E5"
LOCKUP = Lockup((100, 100, 200, 200), DEEP, 7.0)


class StubProvider:
    name = "stub"
    model = resolution = None

    def __init__(self, size=(8, 8)):
        self.prompts, self.size = [], size

    def generate(self, prompt):
        self.prompts.append(prompt)
        return Image.new("RGB", self.size, "black")


@pytest.fixture
def inputs():
    return load_inputs(EXAMPLES / "brief.json", EXAMPLES / "brand.json")


def write_json(path, data):
    path.write_text(json.dumps(data))
    return path


def test_load_resolves_font_to_absolute_path(inputs):
    _, brand = inputs
    font = Path(brand.font)
    assert font.is_absolute() and font.is_file()


def test_load_missing_font_raises(tmp_path):
    brand = json.loads((EXAMPLES / "brand.json").read_text())
    brand_path = write_json(tmp_path / "brand.json", brand)  # relative path now points nowhere
    with pytest.raises(FileNotFoundError, match="font"):
        load_inputs(EXAMPLES / "brief.json", brand_path)


def test_load_rejects_deep_color_outside_palette(tmp_path):
    brief = json.loads((EXAMPLES / "brief.json").read_text())
    brief["products"][0]["deep_color"] = "#1E7F4F"  # the retired brand green
    with pytest.raises(ValueError, match="citrus-soda: deep_color #1E7F4F"):
        load_inputs(write_json(tmp_path / "brief.json", brief), EXAMPLES / "brand.json")


@pytest.mark.parametrize("edit, match", [
    (lambda v: v.pop("HERO_FRUIT"), r"missing \['HERO_FRUIT'\], extra \[\]"),
    (lambda v: v.update(SEED="1"), r"missing \[\], extra \['SEED'\]"),
])
def test_load_rejects_prompt_vars_mismatch(tmp_path, edit, match):
    brief = json.loads((EXAMPLES / "brief.json").read_text())
    edit(brief["products"][1]["prompt_vars"])
    with pytest.raises(ValueError, match=match):
        load_inputs(write_json(tmp_path / "brief.json", brief), EXAMPLES / "brand.json")


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
    brief, brand = inputs
    product = brief.products[0]
    Image.new("RGB", (8, 8), "red").save(tmp_path / f"{product.id}{ext}")
    provider = StubProvider()
    img, hero = get_hero(product, brand, tmp_path, provider, tmp_path / "run")
    assert img.mode == "RGB"
    assert hero.model_dump() == {"product_id": product.id, "source": "reused"}  # source only
    assert provider.prompts == []
    assert not (tmp_path / "run").exists()  # reused heroes are not copied


def test_get_hero_generates_when_missing(inputs, tmp_path):
    brief, brand = inputs
    product = brief.products[0]
    provider = StubProvider()
    provider.model, provider.resolution = "gemini-3-pro-image", "2K"  # non-None: proves it's copied
    img, hero = get_hero(product, brand, tmp_path, provider, tmp_path / "run")
    [prompt] = provider.prompts
    assert hero == GeneratedHero(product_id=product.id, model="gemini-3-pro-image",
                                 resolution="2K", prompt=prompt,  # exact prompt that was sent
                                 path="heroes/citrus-soda.png")
    with Image.open(tmp_path / "run" / hero.path) as saved:
        assert saved.tobytes() == img.tobytes()  # the raw hero, before any fit or lockup
    assert prompt == brand.hero_prompt_template.format(**product.prompt_vars)
    assert "{" not in prompt and "pale lime green" in prompt
    assert "\n\nAVOID: text, lettering" in prompt  # no negative-prompt field: stays in main prompt


SQUARE_CASES = [((1000, 1000), True), ((1010, 1000), True),  # 1% off: accepted
                ((1024, 1536), False), ((1536, 1024), False)]  # portrait / landscape


@pytest.mark.parametrize("size, ok", SQUARE_CASES)
def test_get_hero_requires_square_reused(inputs, tmp_path, size, ok):
    brief, brand = inputs
    Image.new("RGB", size).save(tmp_path / "citrus-soda.png")
    run = tmp_path / "run"
    if ok:
        assert get_hero(brief.products[0], brand, tmp_path, StubProvider(), run)[0].size == size
    else:
        with pytest.raises(ValueError, match=rf"citrus-soda.png is {size[0]}x{size[1]}; .* 1:1"):
            get_hero(brief.products[0], brand, tmp_path, StubProvider(), run)


@pytest.mark.parametrize("size, ok", SQUARE_CASES)
def test_get_hero_requires_square_generated(inputs, tmp_path, size, ok):
    brief, brand = inputs
    provider, run = StubProvider(size), tmp_path / "run"
    if ok:
        assert get_hero(brief.products[1], brand, tmp_path, provider, run)[0].size == size
    else:
        with pytest.raises(ValueError, match=rf"Generated hero for berry-soda is {size[0]}x{size[1]}"):
            get_hero(brief.products[1], brand, tmp_path, provider, run)
    # Saved either way: a paid-for hero is kept even when the square check rejects it.
    with Image.open(run / "heroes" / "berry-soda.png") as saved:
        assert saved.size == size


@pytest.mark.parametrize("ratio", ["1:1", "9:16", "16:9"])
@pytest.mark.parametrize("hero_size", [(1024, 1024), (1600, 900), (500, 1400)])
def test_fit_to_ratio_exact_size(ratio, hero_size):
    assert fit_to_ratio(Image.new("RGB", hero_size), ratio).size == SIZES[ratio]


@pytest.mark.parametrize("ratio", ["1:1", "9:16", "16:9"])
@pytest.mark.parametrize("hero_size", [(1024, 1024), (500, 1400), (1600, 900)])
def test_fit_to_ratio_never_crops(ratio, hero_size):
    w, h = hero_size
    band = round(min(w, h) * 0.05)
    hero = Image.new("RGB", hero_size, "red")
    ImageDraw.Draw(hero).rectangle((band, band, w - band - 1, h - band - 1), fill="black")
    out = fit_to_ratio(hero, ratio)
    x0, y0, x1, y1 = map_box((0, 0, w, h), hero_size, ratio)
    inset = max(2, round(band * (x1 - x0) / w) // 2)
    xm, ym = (x0 + x1) // 2, (y0 + y1) // 2
    for xy in [(xm, y0 + inset), (xm, y1 - 1 - inset), (x0 + inset, ym), (x1 - 1 - inset, ym)]:
        r, g, b = out.getpixel(xy)  # every hero edge survives: nothing was cropped
        assert r > 200 and g < 50 and b < 50, xy


def two_tone(wall=(200, 220, 150), floor=(120, 200, 40), size=(1024, 1024)):
    hero = Image.new("RGB", size, wall)
    ImageDraw.Draw(hero).rectangle((0, size[1] * 0.6, size[0], size[1]), fill=floor)
    return hero


@pytest.mark.parametrize("ratio, pad_xys", [
    ("1:1", {"wall": [(5, 5), (1075, 300)], "floor": [(540, 1075), (5, 1075)]}),  # sides + bottom
    ("9:16", {"wall": [(540, 5), (5, 300)], "floor": [(540, 1915), (1075, 1700)]}),
    ("16:9", {"wall": [(5, 5), (1915, 300)], "floor": [(5, 1075), (1915, 900)]}),
])
def test_fit_to_ratio_pads_wall_above_floor_below(ratio, pad_xys):
    wall, floor = (200, 220, 150), (120, 200, 40)
    out = fit_to_ratio(two_tone(wall, floor), ratio)
    for xy in pad_xys["wall"]:
        assert out.getpixel(xy) == wall, xy
    for xy in pad_xys["floor"]:
        assert out.getpixel(xy) == floor, xy


def test_placement_follows_spec():
    x0, _, x1, _ = map_box((0, 0, 1024, 1024), (1024, 1024), "16:9")
    assert (x0 + x1) / 2 == pytest.approx(0.62 * 1920, abs=1)  # hero center at 62% of width
    # Prompt puts the subject at 20-70% of the hero; on 9:16 it must sit within 30-62% of height.
    _, y0, _, y1 = map_box((0, 205, 1024, 717), (1024, 1024), "9:16")
    assert 0.30 * 1920 <= y0 and y1 <= 0.62 * 1920


def test_subject_box_finds_mock_can_and_plinth():
    hero = MockProvider().generate("citrus")
    box = subject_box(hero)
    expected = (1024 * 0.35, 1024 * 0.20, 1024 * 0.65, 1024 * 0.70)  # plinth width, can top..plinth base
    assert box == pytest.approx(expected, abs=12)


def test_subject_box_none_on_empty_set():
    assert subject_box(two_tone()) is None


@pytest.mark.parametrize("ratio", ["1:1", "9:16", "16:9"])
def test_render_creative_keeps_size_and_input(inputs, ratio):
    _, brand = inputs
    img = fit_to_ratio(Image.new("RGB", (1024, 1024), "black"), ratio)
    before = img.tobytes()
    out, _ = render_creative(img, "Taste the summer", brand, DEEP, ratio)
    assert out.size == SIZES[ratio] and out.mode == "RGB"
    assert img.tobytes() == before


@pytest.mark.parametrize("ratio", ["1:1", "9:16", "16:9"])
@pytest.mark.parametrize("message", ["Prove o verão", "Goûtez l’été", "Schmeck den Sommer ü"])
def test_render_creative_accented_text(inputs, ratio, message):
    _, brand = inputs
    img = fit_to_ratio(Image.new("RGB", (1024, 1024), "black"), ratio)
    assert render_creative(img, message, brand, DEEP, ratio)[0].size == SIZES[ratio]


@pytest.mark.parametrize("ratio", RATIOS)
def test_lockup_zone_inside_frame(ratio):
    W, H = SIZES[ratio]
    (x0, y0, x1, y1), *_ = lockup_zone(ratio, SIZES[ratio])
    assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H


def test_9x16_zone_inside_safe_zone_and_centered():
    (x0, y0, x1, y1), *_ = lockup_zone("9:16", (1080, 1920))
    assert x0 >= 0.06 * 1080 and x1 <= 0.85 * 1080 and y0 >= 0.14 * 1920 and y1 <= 0.65 * 1920
    assert (x0 + x1) / 2 == 540  # centered on the frame, the can's axis
    assert y1 <= 0.30 * 1920 - 0.04 * 1080 + 0.5  # above the subject's 30% line, with the gap
                                                   # (+0.5: zone edges are rounded to pixels)


def test_1x1_hero_top_center_at_scale():
    x0, y0, x1, y1 = map_box((0, 0, 1024, 1024), (1024, 1024), "1:1")
    assert y0 == 0 and (x0 + x1) / 2 == pytest.approx(540, abs=1)  # anchored top-center
    assert x1 - x0 == y1 - y0 == round(HERO_SCALE_1x1 * 1080)


def test_1x1_zone_a_gap_below_hero():
    _, _, _, hero_y1 = map_box((0, 0, 1024, 1024), (1024, 1024), "1:1")
    (_, y0, _, y1), *_ = lockup_zone("1:1", (1080, 1080))
    assert y0 >= hero_y1 + 0.04 * 1080 - 0.5 and y1 == round(0.94 * 1080)  # 6% bottom margin


def test_16x9_zone_left_of_hero_center_half():
    (_, _, x1, _), *_ = lockup_zone("16:9", (1920, 1080))
    hero_x0, _, hero_x1, _ = map_box((0, 0, 1024, 1024), (1024, 1024), "16:9")
    assert x1 + 0.04 * 1080 <= hero_x0 + (hero_x1 - hero_x0) / 4 + 1


@pytest.mark.parametrize("ratio", RATIOS)
@pytest.mark.parametrize("locale", ["en", "es-MX", "pt-BR", "fr-FR", "de-DE"])
def test_lockup_stays_in_zone(inputs, ratio, locale):
    brief, brand = inputs
    _, lockup = render_creative(fit_to_ratio(two_tone(), ratio), brief.message[locale], brand,
                                DEEP, ratio)
    (zx0, zy0, zx1, zy1), *_ = lockup_zone(ratio, SIZES[ratio])
    x0, y0, x1, y1 = lockup.box
    assert zx0 <= x0 and zy0 <= y0 and x1 <= zx1 and y1 <= zy1


def test_long_tagline_two_balanced_lines(inputs):
    _, brand = inputs
    text = "An unusually long summer tagline for this zone"
    ops, _ = _set_lockup(*lockup_zone("9:16", SIZES["9:16"]), text, brand.font, brand.wordmark,
                         TAGLINE_PX["9:16"])
    wordmark, *lines = [t for _, t, _, _ in ops]
    assert wordmark == "FIZZ" and len(lines) == 2 and " ".join(lines) == text
    assert ops[0][2].size == 2 * TAGLINE_PX["9:16"]  # wordmark fixed even when the tagline shrinks
    font = ops[1][2]
    w1, w2 = (font.getlength(ln) for ln in lines)
    assert abs(w1 - w2) < 0.5 * max(w1, w2)  # balanced, not greedy


@pytest.mark.parametrize("ratio", RATIOS)
def test_fixed_type_scale_across_locales(inputs, ratio):
    brief, brand = inputs
    sizes = [[f.size for _, _, f, _ in _set_lockup(*lockup_zone(ratio, SIZES[ratio]), brief.message[loc],
                                                   brand.font, brand.wordmark, TAGLINE_PX[ratio])[0]]
             for loc in brief.locales]
    assert {s[0] for s in sizes} == {2 * TAGLINE_PX[ratio]}  # one wordmark size for every language
    assert {s[1] for s in sizes} == {TAGLINE_PX[ratio]}  # all 5 example taglines fit at target


@pytest.mark.parametrize("bg, expected", [("#000000", CREAM), (CREAM, DEEP)])
def test_lockup_color_by_contrast(inputs, bg, expected):
    _, brand = inputs
    _, lockup = render_creative(Image.new("RGB", SIZES["1:1"], bg), "Taste the summer", brand,
                                DEEP, "1:1")
    assert lockup.color == expected and lockup.contrast >= 4.5


@pytest.mark.parametrize("bg, expected", [("#808080", CREAM), ("#BCBCBC", DEEP)])
def test_lockup_color_both_fail_picks_higher(inputs, bg, expected):
    _, brand = inputs  # mid tones: neither deep (#1F5E2E) nor cream reaches 4.5:1
    _, lockup = render_creative(Image.new("RGB", SIZES["1:1"], bg), "Taste the summer", brand,
                                DEEP, "1:1")
    assert lockup.color == expected and lockup.contrast < 4.5


def test_font_covers_every_message_glyph(inputs):
    # Spec: confirm glyph coverage for all 5 languages. Missing glyphs render as .notdef.
    brief, brand = inputs
    font = ImageFont.truetype(brand.font, 40)

    def glyph(ch):
        img = Image.new("L", (80, 80))
        ImageDraw.Draw(img).text((10, 10), ch, font=font, fill=255)
        return img.tobytes()

    notdef = glyph("")  # private-use codepoint: never in the font
    chars = {c for m in brief.message.values() for c in m if not c.isspace()} | set(brand.wordmark)
    assert [c for c in sorted(chars) if glyph(c) == notdef] == []


@pytest.mark.parametrize("subject, expected", [
    ((150, 150, 300, 300), True),    # boxes intersect
    ((220, 100, 300, 200), True),    # 20 px apart: inside the 4% gap (43 px at 1080)
    ((300, 300, 400, 400), False),   # clear by more than the gap
    (None, None),                    # no subject detected: unknown, not clear
])
def test_check_brand_overlaps_subject(inputs, subject, expected):
    _, brand = inputs
    checks = check_brand(Image.new("RGB", (1080, 1080)), brand, LOCKUP, subject)
    assert checks.overlaps_subject is expected


def test_check_brand_color_share(inputs):
    _, brand = inputs
    share = lambda img: check_brand(img, brand, LOCKUP, None).brand_color_share  # noqa: E731
    assert share(Image.new("RGB", (100, 100), brand.colors[0])) == 1.0
    assert share(Image.new("RGB", (100, 100), "black")) == 0.0


def test_check_brand_never_raises(inputs):
    _, brand = inputs
    broken = brand.model_copy(update={"colors": ["not-a-color"]})
    checks = check_brand(Image.new("RGBA", (3, 3)), broken, LOCKUP, None)
    assert checks.brand_color_share == 0.0 and checks.prohibited_words == []


def test_save_run_writes_creatives_and_manifest(inputs, tmp_path):
    _, brand = inputs
    checks = check_brand(Image.new("RGB", (8, 8)), brand, LOCKUP, None)
    result = CreativeResult(
        product_id="citrus-soda", ratio="9:16", path=creative_path("citrus-soda", "es-MX", "9:16"),
        source="generated", locale="es-MX", checks=checks,
    )
    manifest = save_run([(result, Image.new("RGB", (8, 8)))], [], "fizz", "mock", tmp_path)
    assert (tmp_path / "citrus-soda" / "es-MX" / "9x16" / "citrus-soda_9x16_es-MX.png").is_file()
    assert Manifest.model_validate_json((tmp_path / "manifest.json").read_text()) == manifest
