# Brand icon (favicon / app icon)

Design spec for the square Song History mark. Tracked by
[#586](https://github.com/mshirel/song-history/issues/586); the assets and markup land in a
planned sprint, this document is the decision record the implementer works from.

The app ships **no favicon today** — there is no `rel="icon"` link, no `/favicon.ico` route, and
no icon assets under `src/worship_catalog/web/static/`. Browsers currently request `/favicon.ico`,
get the SPA 404, and fall back to a generic page glyph.

## The source motif

The mark derives from the existing wordmark, `static/highland-logo.png` (375 x 81). That file is a
**horizontal lockup** — a glyph on the left, then "HIGHLAND" over "CHURCH OF CHRIST" in serif caps —
so it cannot be reused as a square icon. But its left glyph is separable and is the identity carrier.

Measured off the PNG (glyph bounding box `x 7..117`, `y 16..70`):

| Property | Measurement |
|---|---|
| Construction | Four round-capped monoline strokes — a stylised mountain range |
| Flank slope | `dx/dy ≈ 0.625` (constant across all four strokes) |
| Stroke weight | 6px against a 52px peak height — a ratio of **0.115** |
| Stroke feet | `x = 10, 28, 48, 114.5` at the baseline |
| Apexes | `x = 39.5, 60.5, 80.5` |

Left to right the strokes are: one bare ascending flank, a small peak, then a large peak. The small
peak's **right shoulder terminates where it crosses the large peak's left flank** — the peaks
overlap, one tucked behind the other. That overlap is the glyph's most distinctive feature and the
square mark keeps it.

Colour comes from the app chrome, not the PNG (which is flat black): **`#1a1a2e`**, the navy already
used for the nav bar, header and footer in `base.html`. A navy tile makes the icon read as part of
the app and holds contrast against both light and dark browser chrome.

## Decision: one skyline, two masters

**Two masters, both drawing the same skyline.** The `>=32px` master is monoline and brand-faithful;
the 16px master is the same skyline filled solid. Same motif, hinted for size — not two marks.

### Why the monoline cannot be used at 16px

This was tested, not assumed. Rendering the monoline at true 16px and sweeping the stroke weight
from 6 to 11 units (of a 64 viewBox) produced **no usable window**:

- at `w <= 8` the strokes land under 2 device pixels and grey out into mush;
- at `w >= 10` the flanks bleed together and the notch between the peaks fills in — the mark stops
  reading as two peaks at all.

The cause is spatial, not stylistic: three flanks plus their gaps have to fit across roughly 11px of
content width. There is not enough resolution. Carrying the wordmark's own 0.115 weight ratio is
even worse — at a 26-unit peak height that is a 3-unit stroke, which renders sub-pixel.

The filled silhouette has no such problem: solid mass survives where line does not.

### Geometry

Both masters use a 64 x 64 viewBox and a `rx="14"` tile filled `#1a1a2e`, marks in `#ffffff`.

**Monoline master** (`icon.svg`) — used at 32px and above.
Apex `y=20`, baseline `y=46`, apexes at `x=26` and `x=40`, flank slope **0.625** (the wordmark's own
angle, unchanged), stroke weight **7.5**. The weight is deliberately hinted — it is ~2.5x the
wordmark's proportional weight, which is the minimum that holds up at 32px.

**Silhouette master** (`icon-16.svg`) — used for the 16px `.ico` frame only.
Apex `y=16`, baseline `y=48`, apexes at `x=24` and `x=40`, flank slope **0.52**.

The 16px master's geometry intentionally departs from the monoline's: taller, a wider apex gap, and
a shallower flank. All three changes exist to keep the **notch between the two summits** open
through rasterisation. At 16px the flank angle is unmeasurable by eye; the notch is the entire read,
so it is what the hinting protects. A sweep of five proportion sets confirmed this one separates the
summits most cleanly.

### The masters

`icon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><rect width="64" height="64" rx="14" fill="#1a1a2e"/><g fill="none" stroke="#ffffff" stroke-width="7.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9.75 46 L26 20 L42.25 46"/><path d="M26 20 L33 31.2"/><path d="M23.75 46 L40 20 L56.25 46"/></g></svg>
```

`icon-16.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><rect width="64" height="64" rx="14" fill="#1a1a2e"/><path d="M7.36 48 L24 16 L40.64 48 Z M23.36 48 L40 16 L56.64 48 Z" fill="#ffffff"/></svg>
```

`icon-maskable.svg` — the monoline master with a **square** tile (`rx="0"`, the platform applies its
own mask) and the artwork scaled to `0.72` about the centre. Verified: at a 192px render the ink
bounding box is `x 40..156, y 62..134`, comfortably inside the 80% safe zone (`19..173`).

## Asset set to produce

| Asset | Source | Notes |
|---|---|---|
| `favicon.ico` | 48 + 32 from `icon.svg`, **16 from `icon-16.svg`** | Multi-resolution, three frames |
| `icon-192.png`, `icon-512.png` | `icon.svg` | Manifest icons |
| `icon-maskable-512.png` | `icon-maskable.svg` | `purpose: maskable` |
| `apple-touch-icon.png` | `icon.svg`, 180 x 180 | Square tile, no transparency |
| `site.webmanifest` | — | `theme_color` / `background_color` `#1a1a2e` |

Generate with a committed script (`cairosvg` to rasterise, Pillow to assemble the `.ico`) rather than
by hand, so the assets are reproducible from the masters.

> **Pillow `.ico` trap** — when assembling a multi-resolution `.ico`, the image you call `.save()` on
> must be the **largest** frame, with the smaller renders passed via `append_images`. Saving from the
> 16px render silently produces a single-frame `.ico` and reports success. This bit the equivalent
> espn-ff work; assert the frame count in a test rather than trusting the write.

Only `base.html` owns a `<head>` in this app, so the link markup has exactly one home — no partial is
needed (unlike espn-ff, which has three `<head>`-owning templates).

Serve `/favicon.ico` from the **root path** as well as `/static/`: browsers request the root path
directly, and the SPA's catch-all would otherwise answer it with a 404.

## Open decision for the implementer: the SVG `rel="icon"` link

Issue #586 asks to "keep the `.svg` as `rel="icon"`". **That conflicts with the two-master design and
should not be done as written.**

Where a browser honours `<link rel="icon" type="image/svg+xml">` it prefers that SVG over the `.ico`
**at every size**, including the 16px tab slot. The hinted 16px frame would then never be used and
the tab icon would be the monoline mush the sweep above rejected.

Recommended: **ship the `.ico` only** and keep the SVG masters in the repo as sources, not as a
served `rel="icon"`. The tab favicon is overwhelmingly rendered at 16-20px, and that is the one size
the mark must not fail at.

Worth knowing before deciding: the failure is scoped to 1x displays. On a HiDPI screen a 16px CSS
favicon is 32 device pixels and the browser picks the 32px frame, which is fine. If the SVG link is
wanted anyway, that is a legitimate call — just make it knowingly, and don't rely on size-based media
queries inside the SVG to switch forms, which is not reliably supported.

## Deployment

Assets are static files served from `src/worship_catalog/web/static/`, so they ship with the image —
no separate deploy step beyond the normal `docs/pi-deploy.md` flow. Browsers cache favicons
aggressively; expect to hard-refresh to see the change on a host that has already cached the 404.
