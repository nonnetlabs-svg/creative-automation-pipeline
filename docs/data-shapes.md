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
               "pt-BR": "Prove o verão", "fr-FR": "Goûtez l'été",
               "de-DE": "Schmeck den Sommer" },
  "aspect_ratios": ["1:1", "9:16", "16:9"],
  "products": [
    { "id": "citrus-soda", "name": "Citrus Soda",
      "description": "sparkling lime soda in a green aluminum can" },
    { "id": "berry-soda", "name": "Berry Soda",
      "description": "mixed berry soda in a purple aluminum can" }
  ]
}
```
Rules: `locales` has at least 1 entry and no duplicates. Each locale is `ll` or `ll-CC`
(e.g. `en`, `pt-BR`) and must have a `message` entry. There is no fallback: a missing one rejects the brief.
The language part must be one of en, es, pt, fr, de, it, nl (`SUPPORTED_LANGUAGES`);
anything else fails with "not supported yet" (see docs/stages.md, CJK and RTL).
`message` must also include `"en"`. `campaign_id` and product `id` use lowercase
letters, digits, and single hyphens only. Campaign id, locale, and product id all become folder names.

Schema versions: only **1.1** is accepted. 1.1 replaced `locale: str` with
`locales: list[str]`. Any other version fails with "unsupported schema_version", and there is no migration path.

## Brand rules — examples/brand.json (owned by the brand team)
`logo` is resolved relative to brand.json's folder.
```json
{
  "colors": ["#1E7F4F", "#FFFFFF"],
  "logo": "../assets/brand/logo.png",
  "prohibited_words": ["guaranteed", "cure", "free"]
}
```

## Manifest — outputs/<campaign_id>/manifest.json (feeds approval + analytics)
```json
{
  "campaign_id": "fizz-summer-2026",
  "provider": "mock",
  "status": "ok",
  "creatives": [{
    "product_id": "citrus-soda", "ratio": "9:16",
    "path": "citrus-soda/es-MX/9x16/creative.png",
    "source": "generated", "locale": "es-MX",
    "checks": { "logo_present": true, "brand_color_share": 0.14,
                "prohibited_words": [] }
  }]
}
```