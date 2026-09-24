# Pipeline stages
One job per stage. Signatures only; bodies come in Step 5.

```python
def load_inputs(brief_path: Path, brand_path: Path) -> tuple[Brief, BrandRules]
def check_copy(brief: Brief, brand: BrandRules) -> list[str]          # bad words found
def get_hero(product: Product, assets_dir: Path,
             provider: ImageProvider) -> tuple[Image, Source]         # "reused" | "generated"
def fit_to_ratio(hero: Image, ratio: str) -> Image                    # smart crop + resize
def render_creative(img: Image, message: str, brand: BrandRules) -> Image
def check_brand(img: Image, brand: BrandRules) -> BrandChecks
def save_run(results: list[CreativeResult], out_dir: Path) -> Manifest

class ImageProvider(Protocol):          # plug-in slot: mock, ElevenLabs, later Firefly
    def generate(self, prompt: str) -> Image: ...
```

## Flow
load → check words (stop if bad, $0 spent) → per product: get hero →
per ratio: crop → add words + logo → check brand → save + manifest