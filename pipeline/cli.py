"""Command line: python -m pipeline run <brief>."""
from enum import Enum
from pathlib import Path

import typer
from dotenv import load_dotenv

from pipeline.providers import ElevenLabsProvider, MockProvider, ProviderError
from pipeline.runner import BlockedCopyError, run_pipeline

app = typer.Typer(no_args_is_help=True)


class ProviderName(str, Enum):
    mock = "mock"
    elevenlabs = "elevenlabs"


PROVIDERS = {ProviderName.mock: MockProvider, ProviderName.elevenlabs: ElevenLabsProvider}


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
) -> None:
    """Generate creatives for every product x locale x aspect ratio in BRIEF."""
    load_dotenv()  # here, not at import: real env vars still win, tests import cli cleanly
    try:
        manifest = run_pipeline(brief, brand, assets, out, PROVIDERS[provider]())
    except (BlockedCopyError, ProviderError) as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1)

    typer.echo(f"{'product':<16}{'locale':<7}{'ratio':<7}{'source':<11}{'logo':<6}color")
    for c in manifest.creatives:
        logo = "yes" if c.checks.logo_present else "NO"
        typer.echo(
            f"{c.product_id:<16}{c.locale:<7}{c.ratio:<7}{c.source:<11}{logo:<6}"
            f"{c.checks.brand_color_share:.2f}"
        )
    typer.echo(f"{len(manifest.creatives)} creatives -> {out / manifest.campaign_id}")
