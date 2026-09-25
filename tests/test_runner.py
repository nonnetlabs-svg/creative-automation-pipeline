import json
from pathlib import Path

import pytest
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
    assert len(list(run_dir.rglob("creative.png"))) == 6
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    assert len(manifest.creatives) == 6
    assert {c.source for c in manifest.creatives} == {"generated"}
    assert all((run_dir / c.path).is_file() for c in manifest.creatives)


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
