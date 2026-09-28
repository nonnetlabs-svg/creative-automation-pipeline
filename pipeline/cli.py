"""Command line: python -m pipeline run <brief>."""
from enum import Enum
from pathlib import Path

import typer
from dotenv import load_dotenv
from pydantic import ValidationError

from pipeline.providers import (
    DEFAULT_MODEL, MODELS, ElevenLabsProvider, MockProvider, ProviderError,
)
from pipeline.runner import run_pipeline

app = typer.Typer(no_args_is_help=True)


class ProviderName(str, Enum):
    mock = "mock"
    elevenlabs = "elevenlabs"


# Built from the registry so the CLI choices and the provider can't drift apart.
ModelName = Enum("ModelName", {m: m for m in MODELS}, type=str)


def _one_line(err: Exception) -> str:
    if isinstance(err, ValidationError):  # pydantic's default is multi-line with doc URLs
        issues = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}"
                           for e in err.errors(include_url=False))
        return f"Invalid {err.title}: {issues}"
    return " ".join(str(err).split())


def make_provider(provider: ProviderName, model: str):
    if provider is ProviderName.elevenlabs:
        return ElevenLabsProvider(model=model)
    return MockProvider()  # ignores model and resolution


@app.callback()
def main() -> None:
    """Creative automation pipeline."""  # keeps `run` as an explicit subcommand


@app.command()
def run(
    brief: Path,
    brand: Path = typer.Option(Path("examples/brand.json"), help="Brand rules JSON."),
    assets: Path = typer.Option(Path("assets/products"), help="Folder of reusable hero images."),
    out: Path = typer.Option(Path("outputs"), help="Output root; run goes in <out>/<campaign_id>."),
    provider: ProviderName = typer.Option(ProviderName.mock, help="Image provider."),
    model: ModelName = typer.Option(DEFAULT_MODEL, help="ElevenLabs image model (mock ignores it)."),
) -> None:
    """Generate creatives for every product x locale x aspect ratio in BRIEF."""
    load_dotenv()  # here, not at import: real env vars still win, tests import cli cleanly
    try:
        manifest = run_pipeline(brief, brand, assets, out, make_provider(provider, model.value))
    # ValueError covers BlockedCopyError, pydantic's ValidationError, the fit and square checks.
    except (ProviderError, ValueError, FileNotFoundError) as err:
        typer.echo(_one_line(err), err=True)
        raise typer.Exit(1)

    typer.echo(f"{'product':<16}{'locale':<7}{'ratio':<7}{'source':<11}{'lockup':<14}"
               f"{'overlap':<9}color")
    for c in manifest.creatives:
        ck = c.checks
        lockup = f"{ck.lockup_color} {ck.lockup_contrast:.1f}"
        overlap = {True: "YES", False: "no", None: "-"}[ck.overlaps_subject]
        typer.echo(
            f"{c.product_id:<16}{c.locale:<7}{c.ratio:<7}{c.source:<11}{lockup:<14}{overlap:<9}"
            f"{ck.brand_color_share:.2f}"
        )
    typer.echo(f"{len(manifest.creatives)} creatives -> {out / manifest.campaign_id}")
