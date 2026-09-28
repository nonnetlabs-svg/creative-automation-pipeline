import json
from pathlib import Path

import pytest
from PIL import Image
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
    assert len(list(run_dir.rglob("creative.png"))) == 30  # 2 products x 5 locales x 3 ratios
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    assert len(manifest.creatives) == 30
    assert len({c.path for c in manifest.creatives}) == 30
    assert {c.locale for c in manifest.creatives} == {"en", "es-MX", "pt-BR", "fr-FR", "de-DE"}
    assert {c.source for c in manifest.creatives} == {"generated"}
    assert all((run_dir / c.path).is_file() for c in manifest.creatives)
    assert "pt-BR" in result.output


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
         "resolution": "2K", "prompt": provider.prompts[0]},
    ]


def test_cli_model_flag_ignored_by_mock(tmp_path):
    out = tmp_path / "out"
    args = ["run", str(EXAMPLES / "brief.json"), "--brand", str(BRAND), "--assets",
            str(tmp_path), "--out", str(out), "--model", "gpt-image-2.5-sunburst"]
    assert CliRunner().invoke(app, args).exit_code == 0
    manifest = Manifest.model_validate_json((out / "fizz-summer-2026" / "manifest.json").read_text())
    assert {(h.model, h.resolution) for h in manifest.heroes} == {(None, None)}


def test_blocked_copy_exits_1_and_writes_nothing(tmp_path, blocked_brief):
    out = tmp_path / "out"
    result = invoke(blocked_brief, out, tmp_path / "no-assets")
    assert result.exit_code == 1
    assert "free" in result.output
    assert not out.exists() or not list(out.rglob("*.png"))


def test_blocked_copy_never_calls_provider(tmp_path, blocked_brief):
    provider = StubProvider()
    with pytest.raises(BlockedCopyError) as exc:
        run_pipeline(blocked_brief, BRAND, tmp_path, tmp_path / "out", provider)
    assert exc.value.words == ["free"]
    assert provider.prompts == []
