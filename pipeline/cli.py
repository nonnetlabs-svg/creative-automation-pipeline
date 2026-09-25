"""Command line: python -m pipeline run <brief>."""
from enum import Enum
from pathlib import Path

import typer

from pipeline.providers import MockProvider
from pipeline.runner import BlockedCopyError, run_pipeline

app = typer.Typer(no_args_is_help=True)


class ProviderName(str, Enum):
    mock = "mock"


PROVIDERS = {ProviderName.mock: MockProvider}


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
    """Generate creatives for every product x aspect ratio in BRIEF."""
    try:
        manifest = run_pipeline(brief, brand, assets, out, PROVIDERS[provider]())
    except BlockedCopyError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1)

    typer.echo(f"{'product':<16}{'ratio':<7}{'source':<11}{'logo':<6}color")
    for c in manifest.creatives:
        logo = "yes" if c.checks.logo_present else "NO"
        typer.echo(f"{c.product_id:<16}{c.ratio:<7}{c.source:<11}{logo:<6}{c.checks.brand_color_share:.2f}")
    typer.echo(f"{len(manifest.creatives)} creatives -> {out / manifest.campaign_id}")
