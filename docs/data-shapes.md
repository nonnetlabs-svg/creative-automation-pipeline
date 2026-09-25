# Data shapes
Principle: real-world shapes, fake infrastructure.

## Brief — examples/brief.json (would come from an intake system)
```json
{
  "schema_version": "1.0",
  "campaign_id": "fizz-summer-2026",
  "market": "MX",
  "locale": "es-MX",
  "audience": "Gen Z, urban, 18-24",
  "message": { "en": "Taste the summer", "es-MX": "Prueba el verano" },
  "aspect_ratios": ["1:1", "9:16", "16:9"],
  "products": [
    { "id": "citrus-soda", "name": "Citrus Soda",
      "description": "sparkling lime soda in a green aluminum can" },
    { "id": "berry-soda", "name": "Berry Soda",
      "description": "mixed berry soda in a purple aluminum can" }
  ]
}
```

## Brand rules — examples/brand.json (owned by the brand team)
`logo` is resolved relative to brand.json's folder.
```json
{
  "colors": ["#1E7F4F", "#FFFFFF"],
  "logo": "assets/brand/logo.png",
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
    "path": "citrus-soda/9x16/creative.png",
    "source": "generated", "locale": "es-MX",
    "checks": { "logo_present": true, "brand_color_share": 0.14,
                "prohibited_words": [] }
  }]
}
```