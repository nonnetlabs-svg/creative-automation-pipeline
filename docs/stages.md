# Pipeline stages
One job per stage. Signatures only; bodies come in Step 5.

```python
def load_inputs(brief_path: Path, brand_path: Path) -> tuple[Brief, BrandRules]
def check_copy(brief: Brief, brand: BrandRules) -> list[str]          # bad words found
def get_hero(product: Product, brief: Brief, assets_dir: Path,
             provider: ImageProvider) -> tuple[Image, Hero]           # ReusedHero | GeneratedHero
def fit_to_ratio(hero: Image, ratio: str) -> Image                    # 1:1, 9:16 center crop; 16:9 contain + blurred fill
def render_creative(img: Image, message: str, brand: BrandRules) -> Image
def check_brand(img: Image, brand: BrandRules) -> BrandChecks         # report only, never raises;
                                     # prohibited_words always [] (check_copy stops the run first)
def save_run(creatives: list[tuple[CreativeResult, Image]], heroes: list[Hero],
             campaign_id: str, provider: str, out_dir: Path) -> Manifest  # out_dir = outputs/<campaign_id>

# Helpers
def creative_path(product_id: str, locale: str, ratio: str) -> str    # "<id>/<locale>/<ratio 9x16>/creative.png"

class ImageProvider(Protocol):          # plug-in slot: mock, ElevenLabs, later Firefly
    model: str | None                   # recorded on generated heroes; None if ignored (mock)
    resolution: str | None
    def generate(self, prompt: str) -> Image: ...
```

## Models (ElevenLabs)
Registry in `providers.MODELS`. Only these two are accepted; any other id fails before a request.

| model_id | name | sent |
|---|---|---|
| `gemini-3-pro-image` (default) | Nano Banana Pro | model_id, prompt, aspect_ratio "1:1", resolution |
| `gpt-image-2.5-sunburst` | GPT Image 2.5 Sunburst | same; `quality` not sent (API default "high") |

Resolution is config only: `DEFAULT_RESOLUTION = "2K"`, because the 9:16 crop needs 1920 px of height.
`gemini-2.5-flash-image` was dropped: it has no resolution field, and Google's Gemini API retires it
from Oct 2, 2026. The mock ignores model and resolution.

No seeds. Neither model accepts one. Reproducibility comes from the human-approved hero
saved in `assets/products/` and reused on every run, not from seeds.

## Flow
load → check words (stop if bad, $0 spent) → per product: get hero (once) →
per locale: message = brief.message[locale] (validated, no fallback) →
per ratio: fit → add words + logo → check brand → save + manifest

check_copy scans every `message` entry, including locales not listed in `locales`.

## Out of scope: CJK and RTL (e.g. Japanese, Hebrew)
- Inter-Bold has no CJK or Hebrew glyphs, so that text would render as empty boxes.
- `_wrap` breaks lines at spaces, and Japanese does not put spaces between words.
- Pillow's basic text layout does no bidi reordering, so Hebrew would render reversed.
Supporting them needs more fonts, libraqm, and new line-break rules, which is a stack.md change.
Brief enforces this at load: a locale whose language is not in `SUPPORTED_LANGUAGES`
(en, es, pt, fr, de, it, nl) fails with "not supported yet". It never renders wrong silently.

## Entry points
```python
def run_pipeline(brief_path: Path, brand_path: Path, assets_dir: Path, out_dir: Path,
                 provider: ImageProvider) -> Manifest     # writes to out_dir/<campaign_id>
class BlockedCopyError(ValueError)                        # .words; raised when check_copy hits
class ProviderError(RuntimeError)                         # provider failed; message never has the key
```
CLI: `python -m pipeline run <brief> [--brand examples/brand.json]
[--assets assets/products] [--out outputs] [--provider mock|elevenlabs]
[--model gemini-3-pro-image|gpt-image-2.5-sunburst]`. `--model` is ignored by mock;
an unknown value is a usage error (exit 2).
`elevenlabs` reads `ELEVENLABS_API_KEY` from `.env` (loaded by the CLI only).
Prints a summary table (product, locale, ratio, source, logo, color); exit 1 on blocked copy or provider error.

A blocked run writes no images and no manifest. Step 7 run logging will record it.