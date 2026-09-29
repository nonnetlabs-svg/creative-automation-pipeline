import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from pipeline.cli import app
from pipeline.models import Manifest
from pipeline.runner import BlockedCopyError, run_pipeline
from tests.test_stages import StubProvider

EXAMPLES = Path(__file__).parent.parent / "examples"
BRAND = EXAMPLES / "brand.json"


@pytest.fixture
def blocked_brief(tmp_path):
    brief = json.loads((EXAMPLES / "brief.json").read_text())
    brief["message"]["en"] = "Free summer"
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief))
    return path


def invoke(brief, out, assets):
    args = ["run", str(brief), "--brand", str(BRAND), "--assets", str(assets), "--out", str(out)]
    return CliRunner().invoke(app, args)


def test_end_to_end_mock(tmp_path):
    result = invoke(EXAMPLES / "brief.json", tmp_path / "out", tmp_path / "no-assets")
    assert result.exit_code == 0, result.output
    run_dir = tmp_path / "out" / "fizz-summer-2026"
    pngs = list(run_dir.rglob("*_*_*.png"))
    assert len([p for p in pngs if "debug" not in p.parts]) == 30  # 2 products x 5 locales x 3 ratios
    assert len(list((run_dir / "debug").rglob("*_debug.png"))) == 30  # one overlay each, outside
    assert manifest_status(run_dir) == "ok"
    assert sorted(p.name for p in (run_dir / "heroes").iterdir()) == [
        "berry-soda.png", "citrus-soda.png"]  # raw generated heroes, for approval
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    assert len(manifest.creatives) == 30
    assert len({c.path for c in manifest.creatives}) == 30
    assert "berry-soda/es-MX/9x16/berry-soda_9x16_es-MX.png" in {c.path for c in manifest.creatives}
    assert {c.locale for c in manifest.creatives} == {"en", "es-MX", "pt-BR", "fr-FR", "de-DE"}
    assert {c.source for c in manifest.creatives} == {"generated"}
    assert all((run_dir / c.path).is_file() for c in manifest.creatives)
    assert "pt-BR" in result.output


def manifest_status(run_dir):
    return json.loads((run_dir / "manifest.json").read_text())["status"]


def test_qa_gate_overlap_exits_3_and_keeps_outputs(tmp_path):
    # A subject spanning the full width (wall and floor still sampled at top/bottom rows)
    # collides with every lockup zone.
    hero = Image.new("RGB", (1024, 1024), (200, 180, 240))
    ImageDraw.Draw(hero).rectangle((0, 100, 1023, 700), fill=(220, 30, 30))
    ImageDraw.Draw(hero).rectangle((0, 900, 1023, 1023), fill=(150, 80, 200))
    assets = tmp_path / "assets"
    assets.mkdir()
    for pid in ("citrus-soda", "berry-soda"):
        hero.save(assets / f"{pid}.png")
    result = invoke(EXAMPLES / "brief.json", tmp_path / "out", assets)
    assert result.exit_code == 3, result.output
    assert "citrus-soda de-DE 16:9 -> debug/citrus-soda/de-DE/16x9/citrus-soda_16x9_de-DE_debug.png" \
        in result.output
    run_dir = tmp_path / "out" / "fizz-summer-2026"
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    flagged = [c for c in manifest.creatives if c.checks.overlaps_subject]
    assert f"QA gate failed: {len(flagged)} creative(s) overlap the subject" in result.output
    assert result.output.count(" -> debug/") == len(flagged)  # each one printed
    # 1:1 never collides: its lockup sits a gap below the whole hero.
    assert flagged and all(c.ratio != "1:1" for c in flagged)
    assert manifest.status == "qa_failed"
    assert len(list(run_dir.glob("*-soda/*/*/*.png"))) == 30  # outputs kept for review
    assert len(list((run_dir / "debug").rglob("*_debug.png"))) == 30


def test_hero_generated_once_per_product_across_locales(tmp_path):
    provider = StubProvider()
    manifest = run_pipeline(EXAMPLES / "brief.json", BRAND, tmp_path, tmp_path / "out", provider)
    assert len(manifest.creatives) == 30
    assert len(provider.prompts) == 2  # not 10: one hero per product, shared by all locales


def test_manifest_records_generation_for_generated_heroes_only(tmp_path):
    Image.new("RGB", (8, 8), "red").save(tmp_path / "citrus-soda.png")  # reused; berry is generated
    provider = StubProvider()
    provider.model, provider.resolution = "gpt-image-2.5-sunburst", "2K"
    run_pipeline(EXAMPLES / "brief.json", BRAND, tmp_path, tmp_path / "out", provider)
    saved = json.loads((tmp_path / "out" / "fizz-summer-2026" / "manifest.json").read_text())
    assert saved["heroes"] == [
        {"product_id": "citrus-soda", "source": "reused"},
        {"product_id": "berry-soda", "source": "generated", "model": "gpt-image-2.5-sunburst",
         "resolution": "2K", "prompt": provider.prompts[0], "path": "heroes/berry-soda.png"},
    ]
    run_dir = tmp_path / "out" / "fizz-summer-2026"
    assert [p.name for p in (run_dir / "heroes").iterdir()] == ["berry-soda.png"]  # reused: no copy


def test_cli_model_flag_ignored_by_mock(tmp_path):
    out = tmp_path / "out"
    args = ["run", str(EXAMPLES / "brief.json"), "--brand", str(BRAND), "--assets",
            str(tmp_path), "--out", str(out), "--model", "gpt-image-2.5-sunburst"]
    assert CliRunner().invoke(app, args).exit_code == 0
    manifest = Manifest.model_validate_json((out / "fizz-summer-2026" / "manifest.json").read_text())
    assert {(h.model, h.resolution) for h in manifest.heroes} == {(None, None)}


@pytest.mark.parametrize("flag, expected", [
    ([], "gpt-image-2.5-sunburst"),  # default comes from brand.json hero_model
    (["--model", "gemini-3-pro-image"], "gemini-3-pro-image"),  # --model overrides it
])
def test_cli_model_defaults_to_brand_hero_model(tmp_path, monkeypatch, flag, expected):
    seen = []
    monkeypatch.setattr("pipeline.cli.make_provider",
                        lambda provider, model: seen.append(model) or StubProvider())
    args = ["run", str(EXAMPLES / "brief.json"), "--brand", str(BRAND), "--assets",
            str(tmp_path), "--out", str(tmp_path / "out"), *flag]
    assert CliRunner().invoke(app, args).exit_code == 0
    assert seen == [expected]  # one model for the whole run


def test_blocked_copy_exits_1_and_writes_nothing(tmp_path, blocked_brief):
    out = tmp_path / "out"
    result = invoke(blocked_brief, out, tmp_path / "no-assets")
    assert result.exit_code == 1
    assert "free" in result.output
    assert not out.exists() or not list(out.rglob("*.png"))


def test_tagline_too_long_fails_at_load(tmp_path):
    brief = json.loads((EXAMPLES / "brief.json").read_text())
    brief["message"]["de-DE"] = "Schmeck den langen heißen Sommer " * 12
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief))
    provider = StubProvider()
    with pytest.raises(ValueError, match=r"de-DE 1:1: tagline .* does not fit"):
        run_pipeline(path, BRAND, tmp_path, tmp_path / "out", provider)
    assert provider.prompts == []  # failed before any generation: $0
    assert not (tmp_path / "out").exists()


def write_brief(tmp_path, edit):
    brief = json.loads((EXAMPLES / "brief.json").read_text())
    edit(brief)
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief))
    return path


@pytest.mark.parametrize("case, expected", [
    ("invalid_brief", r"^Invalid Brief: message: Value error, message uses ASCII quotes"),  # ValidationError
    ("non_square_hero", r"^Hero .*citrus-soda.png is 1536x1024; heroes must be 1:1"),  # ValueError
    ("missing_brief", r"^\[Errno 2\] No such file or directory: .*nope.json"),  # FileNotFoundError
])
def test_cli_input_errors_exit_1_one_line(tmp_path, case, expected):
    assets, brief = tmp_path / "assets", EXAMPLES / "brief.json"
    assets.mkdir()
    if case == "invalid_brief":
        brief = write_brief(tmp_path, lambda b: b["message"].update(en="Taste 'summer'"))
    elif case == "non_square_hero":
        Image.new("RGB", (1536, 1024)).save(assets / "citrus-soda.png")
    else:
        brief = tmp_path / "nope.json"
    result = invoke(brief, tmp_path / "out", assets)
    assert result.exit_code == 1
    assert "Traceback" not in result.output and result.output.count("\n") == 1  # one clean line
    assert re.match(expected, result.output), result.output


def test_blocked_copy_never_calls_provider(tmp_path, blocked_brief):
    provider = StubProvider()
    with pytest.raises(BlockedCopyError) as exc:
        run_pipeline(blocked_brief, BRAND, tmp_path, tmp_path / "out", provider)
    assert exc.value.words == ["free"]
    assert provider.prompts == []
