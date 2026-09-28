# FIZZ Creative Spec (frozen)

How to read this doc: B1 is the base spec. B2 supersedes B1's BAND, TAGLINE,
LOGO, and LAYOUT PER RATIO sections. The final section, "Scope for this build:
B2-lite", decides what is built now. Anything tagged [DEFERRED] is a README
next step, not part of this build.

---

## B1 — Creative decisions

1. Flavor colors: Lime #1F5E2E (forest), Berry #3A1450 (blackberry).
   Tagline text #FFF6E5 (cream) on both. Backdrop, floor and can colors come
   from the hero prompt, not code.
2. Art-direction line: "Flavor worlds: one can, one color, hard sun, and a
   wink of play."
3. Logo: [SUPERSEDED by B2 type lockup]
4. Band: [SUPERSEDED by B2: no band]

## B1 — Engineering spec

GOAL
One AI-generated 1:1 hero per product → code composes 1:1, 9:16, 16:9
× 5 languages. Code owns all brand color, type and logo. The AI image
contains no text.

PRODUCTS / PALETTE
                 LIME        BERRY
deep color       #1F5E2E     #3A1450   (type lockup color)
cream fallback   #FFF6E5     #FFF6E5
(backdrop, floor, can and accent colors are set by the prompt, not code)

HERO GENERATION
- Use the master prompt template plus per-product fill-ins (below).
- Same model/settings for both products; only the prompt variables change.
- Hero is 1:1, generated at the highest available resolution
  (2K preferred; flag in README if 1K).
- QA gate: OCR text detection → reject/regenerate. [DEFERRED: the human
  hero approval is the QA gate for this build]
- No retouching.

BAND, TAGLINE, LOGO, LAYOUT PER RATIO: [SUPERSEDED by B2 below]

OUTPUT
2 products × 3 ratios × 5 languages = 30 assets.
Organized in folders (required by the brief), with descriptive filenames:
<product>/<locale>/<ratio>/<product>_<ratio>_<locale>.png
e.g. citrus-soda/es-MX/9x16/citrus-soda_9x16_es-MX.png

---

## B2 — Type & layout (supersedes B1 band, tagline, logo, layout)

PRINCIPLE
No band. Logo + tagline form one TYPE LOCKUP set directly on the backdrop
color. The hero is never cropped; every ratio is built by scaling the hero
and edge-padding the set (wall color extends up/sides, floor color extends
down/sides).

TYPE LOCKUP
- Stack: FIZZ wordmark on top, tagline below, same color, one group.
- Typeface: Bricolage Grotesque ExtraBold (Google Fonts, OFL), at
  assets/fonts/BricolageGrotesque-ExtraBold.ttf. Confirm glyph coverage for
  all 5 languages' accented characters.
- Color: product deep color (Lime #1F5E2E, Berry #3A1450). Contrast check
  vs. pixels behind the lockup; below 4.5:1 → cream #FFF6E5.
- Tagline: sentence case, up to 2 lines, balanced line breaks, tight
  leading (~1.0). Auto-scale down to fit the zone; never overflow.
- Wordmark width ≈ 60% of tagline block width.
- Typographic punctuation validated before render (’ not ').

SUBJECT DETECTION
- Sample wall color (top rows) and floor color (bottom rows) of the hero.
- Pixels differing beyond tolerance = subject (can, plinth, props,
  shadows). Compute subject bounding box.
- Lockup box must not overlap the subject box (min gap: 4% of short edge).
  [B2-lite: compute the box and REPORT overlap in the manifest only]
- If it can't fit at minimum type size → fallback: solid deep-color band
  behind the tagline only, log a warning. [DEFERRED]

LAYOUT PER RATIO
- 1:1 (1080×1080): hero as-is. Lockup centered horizontally in the floor
  zone below the subject, bottom margin 6%.
- 9:16 (1080×1920): hero scaled to 1080 wide, placed so the subject sits
  between 30% and 62% of frame height. Pad above with wall color, below
  with floor color.
  Platform safe zone (Reels/TikTok, conservative): keep all type out of
  top 14%, bottom 35%, left 6%, right 15%.
  Lockup centered, inside the safe zone, between the top safe line and
  the subject.
- 16:9 (1920×1080): hero scaled to full height, positioned with its center
  at 62% of frame width. Edge-pad left and right.
  Lockup left-aligned, left margin 8%, vertically centered, not
  overlapping the subject.

SUPERSEDED — DO NOT IMPLEMENT
- Full-width tagline band (any height) as the default treatment
- Logo as a separate top-right element (logo.png overlay)
- 9:16 center crop
- 16:9 blurred fill
- Taller 9:16 band proposal
- "Never wrap" tagline rule (2 lines now allowed)
- Single brand-green band / green logo on all outputs
- Grey/concrete sets, fruit-splash compositions

---

## Hero prompt (final template, B2 composition applied)

MASTER PROMPT TEMPLATE
Bold color-blocked studio product photograph of a single unbranded aluminum
soda can, centered, front-facing, eye-level, 50mm lens.

SET: seamless two-tone set — flat {WALL_COLOR} wall meeting a flat
{FLOOR_COLOR} floor in a clean horizontal line. Solid colors only, no
gradient, no vignette, no texture, edges of frame completely empty.

CAN: glossy {CAN_COLOR} can decorated with large playful abstract
paper-cutout shapes — {CAN_SHAPES} — in {ACCENT_COLOR} and cream. Graphic
shapes only, absolutely no letters, words, numbers, logos or symbols.
Heavy fresh condensation beads on the can only.

PROPS: can stands on a short matte cylindrical plinth in {FLOOR_COLOR}.
Beside it, {HERO_FRUIT}. Behind the can, a few flat matte paper-cutout
{CUTOUT_SHAPES} in {ACCENT_COLOR} and a slightly deeper wall tone, floating
close to the can. All props within the center half of the frame.

LIGHT: hard direct sunlight from upper left, crisp defined cast shadows to
the lower right, bright and high-key, saturated but clean color.

COMPOSITION: square 1:1, can occupies about 25% of frame width, top of can
at roughly 20% of frame height, plinth base at roughly 70% of frame height.
Bottom quarter of the frame is empty flat floor. Generous empty color above
and to the sides. All props within the center half of the frame. Minimal,
whimsical, premium, editorial — in the spirit of modern craft soda
packaging campaigns.

AVOID: text, lettering, typography, labels, logos, watermarks, splashes,
liquid explosions, scattered droplets on the set, busy backgrounds,
gradients, grey tones, moody lighting, multiple cans.

FILL-INS
                 LIME                                BERRY
WALL_COLOR       pale lime green                     soft lilac
FLOOR_COLOR      bright chartreuse                   orchid purple
CAN_COLOR        vivid green                         deep violet
CAN_SHAPES       bold lime-slice circles and         bold berry-cluster dots
                 leaf shapes                         and leaf shapes
ACCENT_COLOR     watermelon pink                     citrus yellow
HERO_FRUIT       one oversized fresh lime half,      one oversized glossy
                 cut face toward camera              blackberry with two
                                                     raspberries
CUTOUT_SHAPES    lime-slice and leaf shapes          berry-cluster and leaf
                                                     shapes

GENERATION RULES
- Store the template and fill-ins as config; substitute variables at
  runtime. Do not hand-edit per product.
- Same model and settings for both products.
- If the model has a negative-prompt field, send the AVOID line there and
  keep it in the main prompt as well. If not, main prompt only.
- Use color words in prompts, not hex codes. Exact brand hex values are
  applied by the compositor only.
- Log prompt, seed (if supported) and model with each generated hero.
- Generate 2–3 seeds per product; a human picks the hero. [DEFERRED as a
  command; for this build, the human approves a hero by placing it in
  assets/products/<product-id>.png, which the pipeline then reuses]
- If berry's can doesn't separate from the backdrop, change CAN_COLOR to a
  darker violet; do not lighten the backdrop.

---

## Scope for this build: B2-lite (frozen)

Build now:
- One fit for all ratios: scale hero, edge-pad (wall color above/sides,
  floor color below/sides). Never crop.
- Type lockup (FIZZ wordmark + tagline, Bricolage Grotesque ExtraBold),
  product deep color, cream #FFF6E5 if contrast < 4.5:1.
- FIXED lockup zones per ratio from B2's numbers, in one function
  lockup_zone(ratio, size), so subject-aware placement can replace it later.
- subject_box(hero) computed and used ONLY to report overlap in the manifest.
- Prompt template + per-product fill-ins as config; typographic punctuation
  check.
- Filenames: <product>/<locale>/<ratio>/<product>_<ratio>_<locale>.png

Deferred (README next steps, do NOT build):
- Collision-avoiding auto-layout and the fallback band
- OCR text gate
- Multi-seed candidate generation command

Spec is frozen. New creative ideas go to README next steps.