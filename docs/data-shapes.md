# Data shapes
Principle: real-world shapes, fake infrastructure.

## Brief — examples/brief.json (would come from an intake system)
```json
{
  "schema_version": "1.1",
  "campaign_id": "fizz-summer-2026",
  "market": "Global",
  "locales": ["en", "es-MX", "pt-BR", "fr-FR", "de-DE"],
  "audience": "Gen Z, urban, 18-24",
  "message": { "en": "Taste the summer", "es-MX": "Prueba el verano",
               "pt-BR": "Prove o verão", "fr-FR": "Goûtez l’été",
               "de-DE": "Schmeck den Sommer" },
  "aspect_ratios": ["1:1", "9:16", "16:9"],
  "products": [
    { "id": "citrus-soda", "name": "Citrus Soda",
      "description": "sparkling lime soda in a green aluminum can",
      "deep_color": "#1F5E2E",
      "prompt_vars": { "WALL_COLOR": "pale lime green", "FLOOR_COLOR": "bright chartreuse",
                       "...": "one entry per template placeholder" } },
    { "id": "berry-soda", "...": "same shape, deep_color #3A1450" }
  ]
}
```
Copy: `message` text must use typographic punctuation (’ “ ”); an ASCII `'` or `"` rejects the brief.
`deep_color` is the lockup color and must be one of the brand `colors`. `prompt_vars` keys must exactly
match the placeholders in the brand's `hero_prompt_template`; a missing or extra key fails at load.
Both checks cross files, so `load_inputs` runs them, not the models.
Rules: `locales` has at least 1 entry and no duplicates. Each locale is `ll` or `ll-CC`
(e.g. `en`, `pt-BR`) and must have a `message` entry. There is no fallback: a missing one rejects the brief.
The language part must be one of en, es, pt, fr, de, it, nl (`SUPPORTED_LANGUAGES`);
anything else fails with "not supported yet" (see docs/stages.md, CJK and RTL).
`message` must also include `"en"`. `campaign_id` and product `id` use lowercase
letters, digits, and single hyphens only. Campaign id, locale, and product id all become folder names.

Schema versions: only **1.1** is accepted. 1.1 replaced `locale: str` with
`locales: list[str]`. Any other version fails with "unsupported schema_version", and there is no migration path.

## Brand rules — examples/brand.json (owned by the brand team)
`font` is resolved relative to brand.json's folder and must exist (fails at load). There is no logo
file: the typeset `wordmark` is the logo (docs/creative-spec.md, B2).
```json
{
  "colors": ["#1F5E2E", "#3A1450", "#FFF6E5"],
  "text_fallback_color": "#FFF6E5",
  "wordmark": "FIZZ",
  "font": "../assets/fonts/BricolageGrotesque-ExtraBold.ttf",
  "hero_prompt_template": "Bold color-blocked studio product photograph ... flat {WALL_COLOR} wall ...\n\nAVOID: text, lettering, ...",
  "prohibited_words": ["guaranteed", "cure", "free"]
}
```
`hero_prompt_template` is the spec's final template, filled with each product's `prompt_vars`.
The AVOID line stays in the main prompt, because the image API has no negative-prompt field.

## Manifest — outputs/<campaign_id>/manifest.json (feeds approval + analytics)
```json
{
  "campaign_id": "fizz-summer-2026",
  "provider": "elevenlabs",
  "status": "ok",
  "heroes": [
    { "product_id": "citrus-soda", "source": "reused" },
    { "product_id": "berry-soda", "source": "generated",
      "model": "gemini-3-pro-image", "resolution": "2K",
      "prompt": "Bold color-blocked studio product photograph ... soft lilac wall ...",
      "path": "heroes/berry-soda.png" }
  ],
  "creatives": [{
    "product_id": "berry-soda", "ratio": "9:16",
    "path": "berry-soda/es-MX/9x16/berry-soda_9x16_es-MX.png",
    "source": "generated", "locale": "es-MX",
    "checks": { "lockup_contrast": 7.8, "lockup_color": "#3A1450",
                "overlaps_subject": false, "brand_color_share": 0.14,
                "prohibited_words": [] }
  }]
}
```
`lockup_color` is the product's `deep_color`, or `text_fallback_color` when contrast against the
pixels behind the lockup is below 4.5:1. `lockup_contrast` is the WCAG ratio of the color used
(it can still be < 4.5 if cream also fails; the fallback band is deferred). `overlaps_subject`
is report only (B2-lite), counts the spec's 4% gap, and is `null` when no subject was detected.
`heroes` is required, with one entry per product. A reused hero has only `product_id` and `source`
(the file in `assets/products/` is the record), and extra fields are rejected. A generated hero
adds `model`, `resolution`, the exact `prompt` sent, in full, and `path`: the raw hero saved at
`outputs/<campaign_id>/heroes/<product-id>.png` right after generation, before any check or render,
so a paid hero survives a failed run. A human approves it by copying it to `assets/products/`.
Reused heroes are not copied. With `provider: "mock"`,
`model` and `resolution` are `null`: the mock ignores them, so it never claims a real model.
There is no `seed` field (see docs/stages.md, Models).