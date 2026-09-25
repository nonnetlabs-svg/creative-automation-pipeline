# Pipeline stages
One job per stage. Signatures only; bodies come in Step 5.

```python
def load_inputs(brief_path: Path, brand_path: Path) -> tuple[Brief, BrandRules]
def check_copy(brief: Brief, brand: BrandRules) -> list[str]          # bad words found
def get_hero(product: Product, brief: Brief, assets_dir: Path,
             provider: ImageProvider) -> tuple[Image, Source]         # "reused" | "generated"
def fit_to_ratio(hero: Image, ratio: str) -> Image                    # center crop + resize
def render_creative(img: Image, message: str, brand: BrandRules) -> Image
def check_brand(img: Image, brand: BrandRules) -> BrandChecks         # report only, never raises;
                                     # prohibited_words always [] (check_copy stops the run first)
def save_run(creatives: list[tuple[CreativeResult, Image]], campaign_id: str,
             provider: str, out_dir: Path) -> Manifest                # out_dir = outputs/<campaign_id>

# Helpers
def pick_message(brief: Brief) -> tuple[str, str]                     # brief.locale if present, else "en"
def creative_path(product_id: str, ratio: str) -> str                 # "<id>/<ratio 9x16>/creative.png"

class ImageProvider(Protocol):          # plug-in slot: mock, ElevenLabs, later Firefly
    def generate(self, prompt: str) -> Image: ...
```

## Flow
load → check words (stop if bad, $0 spent) → per product: get hero →
per ratio: crop → add words + logo → check brand → save + manifest

## Entry points
```python
def run_pipeline(brief_path: Path, brand_path: Path, assets_dir: Path, out_dir: Path,
                 provider: ImageProvider) -> Manifest     # writes to out_dir/<campaign_id>
class BlockedCopyError(ValueError)                        # .words; raised when check_copy hits
class ProviderError(RuntimeError)                         # provider failed; message never has the key
```
CLI: `python -m pipeline run <brief> [--brand examples/brand.json]
[--assets assets/products] [--out outputs] [--provider mock|elevenlabs]`.
`elevenlabs` reads `ELEVENLABS_API_KEY` from `.env` (loaded by the CLI only).
Prints a summary table; exit 1 on blocked copy or provider error.

A blocked run writes no images and no manifest. Step 7 run logging will record it.