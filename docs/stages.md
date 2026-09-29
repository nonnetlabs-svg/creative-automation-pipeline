# Pipeline stages
One job per stage. Signatures only; bodies come in Step 5.

```python
def load_inputs(brief_path: Path, brand_path: Path) -> tuple[Brief, BrandRules]  # also: font exists,
                                     # deep_color in palette, prompt_vars match template, every
                                     # locale x ratio tagline fits its lockup zone at >= MIN_TYPE
def check_copy(brief: Brief, brand: BrandRules) -> list[str]          # bad words found
def get_hero(product: Product, brand: BrandRules, assets_dir: Path, provider: ImageProvider,
             run_dir: Path) -> tuple[Image, Hero]                     # ReusedHero | GeneratedHero;
                                     # generated: saved to run_dir/heroes/<id>.png before any check;
                                     # prompt = brand.hero_prompt_template filled with product.prompt_vars;
                                     # reused or generated, a hero must be 1:1 within 1% (ValueError).
                                     # Approval (manual): copy heroes/<id>.png to assets/products/<id>.png
                                     # plus a sidecar assets/products/<id>.json = that run's heroes[] entry
                                     # (model, resolution, prompt; path -> source run folder), committed
                                     # together. The pipeline never reads the sidecar; reused manifest
                                     # entries stay source-only. Production equivalent: C2PA Content Credentials.
def fit_to_ratio(hero: Image, ratio: str) -> Image                    # never crops: contain-scale, place, edge-pad
                                     # (averaged edge strip stretched: wall up/sides, floor down/sides).
                                     # 9:16 subject at ~32-60% of height; 16:9 hero center at 62% of width
def subject_box(hero: Image) -> Box | None                            # pixels unlike sampled wall (top rows) and
                                     # floor (bottom rows); used ONLY to report overlap (B2-lite)
def map_box(box: Box, hero_size, ratio: str) -> Box                   # hero coords -> creative coords, same placement
def lockup_zone(ratio: str, size) -> tuple[Box, str, str]            # fixed zone + (h, v) align from spec B2;
                                     # one function so subject-aware placement can replace it
def render_creative(img: Image, message: str, brand: BrandRules, deep_color: str,
                    ratio: str) -> tuple[Image, Lockup]               # FIZZ over <=2 balanced tagline lines;
                                     # deep color, cream if contrast vs. pixels behind < 4.5:1
def check_brand(img: Image, brand: BrandRules, lockup: Lockup,
                subject: Box | None) -> BrandChecks                   # report only, never raises;
                                     # prohibited_words always [] (check_copy stops the run first)
def save_run(creatives: list[tuple[CreativeResult, Image]], heroes: list[Hero],
             campaign_id: str, provider: str, out_dir: Path) -> Manifest  # out_dir = outputs/<campaign_id>

# Helpers
def creative_path(product_id: str, locale: str, ratio: str) -> str    # "<id>/<locale>/<9x16>/<id>_<9x16>_<locale>.png"

class ImageProvider(Protocol):          # plug-in slot: mock, ElevenLabs, later Firefly
    model: str | None                   # recorded on generated heroes; None if ignored (mock)
    resolution: str | None
    def generate(self, prompt: str) -> Image: ...
```

## Models (ElevenLabs)
Registry in `providers.MODELS`. Only these two are accepted; any other id fails before a request.
The default is brand.json `hero_model` (B5: Sunburst); `--model` overrides it for one run.
There is no default in code.

| model_id | name | sent |
|---|---|---|
| `gemini-3-pro-image` | Nano Banana Pro | model_id, prompt, aspect_ratio "1:1", resolution |
| `gpt-image-2.5-sunburst` (brand default) | GPT Image 2.5 Sunburst | same; `quality` not sent (API default "high") |

Resolution is config only: `DEFAULT_RESOLUTION = "2K"`. No ratio crops; each scales the 1:1 hero to
1080 px per side, so 2K downsamples with headroom (1K would be a slight ~1.05x upscale).
`gemini-2.5-flash-image` was dropped: it has no resolution field, and Google's Gemini API retires it
from Oct 2, 2026. The mock ignores model and resolution.

No seeds. Neither model accepts one. Reproducibility comes from the human-approved hero
saved in `assets/products/` and reused on every run, not from seeds.

## Flow
load (incl. tagline fit check) → check words (stop if bad, $0 spent) →
per product: get hero (once), subject box (once) →
per locale: message = brief.message[locale] (validated, no fallback) →
per ratio: fit → add type lockup → check brand → save + manifest

The tagline fit is checked at load because zones are fixed and the font is known; render
repeats it only as a safety assert.

check_copy scans every `message` entry, including locales not listed in `locales`.

## Out of scope: CJK and RTL (e.g. Japanese, Hebrew)
- Bricolage Grotesque has no CJK or Hebrew glyphs, so that text would render as empty boxes.
- The lockup breaks lines at spaces, and Japanese does not put spaces between words.
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
[--model gemini-3-pro-image|gpt-image-2.5-sunburst]`. `--model` overrides brand.json `hero_model`
and is ignored by mock; an unknown value is a usage error (exit 2).
`elevenlabs` reads `ELEVENLABS_API_KEY` from `.env` (loaded by the CLI only).
Prints a summary table (product, locale, ratio, source, lockup color + contrast, overlap, color).
Exit 1 with one clean line on blocked copy, provider error, invalid input (pydantic), a tagline
that can't fit, a non-square hero, or a missing file.

A run blocked at load (copy or tagline fit) writes nothing. A run that fails after generation
writes no creatives and no manifest, but keeps the paid heroes in `heroes/`. Step 7 run logging will record it.