# Brand icon (favicon / app icon)

Design spec for the square Song History mark. Tracked by
[#586](https://github.com/mshirel/song-history/issues/586); the assets and markup land in a
planned sprint, this document is the decision record the implementer works from.

The app ships **no favicon today** — there is no `rel="icon"` link, no `/favicon.ico` route, and
no icon assets under `src/worship_catalog/web/static/`. Browsers request `/favicon.ico`, get the
catch-all 404, and fall back to a generic page glyph.

## The mark

**A song book: a music note on a book cover.** A white portrait cover, corners lightly rounded,
carrying a single knocked-out eighth note, on a rounded navy tile.

It is chosen for being unambiguous at the size that matters. A tab favicon is a ~16px glyph, and at
that size an icon gets one idea, not two — this one reads as a hymnal or sheet-music cover, which is
what the app catalogues.

Colour is **`#1a1a2e`**, taken from the app chrome rather than invented: it is already the navy used
for the nav bar, header and footer in `base.html`. A solid navy tile makes the icon look native to
the app and holds contrast against both light and dark browser chrome, which a transparent or
white-ground mark would not.

The mark is **not** derived from the Highland wordmark. See
[Rejected direction](#rejected-direction-the-wordmark-peaks) below for why, and for what to do if a
visual tie to the church's mark is wanted later.

## Decision: two masters

| Master | Used at | Why |
|---|---|---|
| `icon.svg` | 32px and above | The mark as drawn |
| `icon-16.svg` | the 16px `.ico` frame only | The same mark, redrawn for the pixel grid |

Scaled straight down, the note's **stem falls under two device pixels and greys out** — the note
stops reading as a note. The 16px master therefore redraws it with a fatter stem and a slightly
larger head, on a marginally larger cover. This is icon hinting: at 16px you redraw for the grid
rather than resample onto it. Both were rasterised at true 16px and compared before this was
settled; the hinted one is legibly better, not theoretically better.

### Geometry

Both masters use a 64 x 64 viewBox, a `rx="14"` tile filled `#1a1a2e`, and a white cover with the
note knocked out in the tile navy.

| | Cover | Note scale | Stem width | Head radii |
|---|---|---|---|---|
| `icon.svg` | `x 15, y 10`, `34 x 44`, `rx 3` | 1.35 | 3.2 | 6.0 x 4.6 |
| `icon-16.svg` | `x 14, y 9`, `36 x 46`, `rx 3` | 1.45 | 4.4 | 6.6 x 5.2 |

The cover's ~3:4 proportion is deliberate — squarer reads as a card, narrower wastes the tile. The
note is sized to the largest that still leaves margin; one step larger and the flag touches the
cover edge.

### The masters

`icon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><rect width="64" height="64" rx="14" fill="#1a1a2e"/><rect x="15" y="10" width="34" height="44" rx="3" fill="#ffffff"/><g fill="#1a1a2e" transform="translate(32 32) scale(1.35)"><rect x="-1.6" y="-13" width="3.2" height="17" rx="1"/><path d="M1.6 -13 L10 -9.6 L10 -3.4 L1.6 -6.8 Z"/><ellipse cx="-4.6" cy="5" rx="6" ry="4.6" transform="rotate(-20 -4.6 5)"/></g></svg>
```

`icon-16.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><rect width="64" height="64" rx="14" fill="#1a1a2e"/><rect x="14" y="9" width="36" height="46" rx="3" fill="#ffffff"/><g fill="#1a1a2e" transform="translate(32 32) scale(1.45)"><rect x="-2.2" y="-13" width="4.4" height="17" rx="1"/><path d="M2.2 -13 L10 -9.6 L10 -3.4 L2.2 -6.8 Z"/><ellipse cx="-4.6" cy="5" rx="6.6" ry="5.2" transform="rotate(-20 -4.6 5)"/></g></svg>
```

`icon-maskable.svg` — `icon.svg` with a **square** tile (no `rx`; the platform applies its own mask)
and the artwork scaled to `0.72` about the centre. Verified: at a 192px render the ink bounding box
is `x 59..132, y 48..143`, comfortably inside the 80% safe zone (`19..173`).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><rect width="64" height="64" fill="#1a1a2e"/><g transform="translate(32 32) scale(0.72) translate(-32 -32)"><rect x="15" y="10" width="34" height="44" rx="3" fill="#ffffff"/><g fill="#1a1a2e" transform="translate(32 32) scale(1.35)"><rect x="-1.6" y="-13" width="3.2" height="17" rx="1"/><path d="M1.6 -13 L10 -9.6 L10 -3.4 L1.6 -6.8 Z"/><ellipse cx="-4.6" cy="5" rx="6" ry="4.6" transform="rotate(-20 -4.6 5)"/></g></g></svg>
```

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
directly, and the catch-all would otherwise answer it with a 404.

## Open decision for the implementer: the SVG `rel="icon"` link

Issue #586 asks to "keep the `.svg` as `rel="icon"`". **That conflicts with the two-master design and
should not be done as written.**

Where a browser honours `<link rel="icon" type="image/svg+xml">` it prefers that SVG over the `.ico`
**at every size**, including the 16px tab slot. The hinted 16px master would then never be used and
the tab icon would be the greyed-out stem the hinting exists to prevent.

Recommended: **ship the `.ico` only** and keep the SVG masters in the repo as sources, not as a
served `rel="icon"`.

Worth knowing before deciding: the failure is scoped to 1x displays. On a HiDPI screen a 16px CSS
favicon is 32 device pixels and the browser picks the 32px frame, which is fine. If the SVG link is
wanted anyway, that is a legitimate call — just make it knowingly, and don't rely on size-based media
queries inside the SVG to switch forms, which is not reliably supported.

## Rejected direction: the wordmark peaks

The first attempt derived the icon from the existing wordmark, `static/highland-logo.png`. That file
is a horizontal lockup — a glyph, then "HIGHLAND" over "CHURCH OF CHRIST" — so the lockup itself
cannot be squared, but its **left glyph** is separable: a monoline mountain range of four
round-capped strokes on a constant `dx/dy ≈ 0.625` flank, the small peak's right shoulder tucking
behind the large peak.

Two problems killed it, in order:

1. **The monoline could not survive 16px.** Sweeping stroke weight from 6 to 11 units of a 64
   viewBox found no usable window — thin weights grey out below two device pixels, heavy weights
   bleed the flanks together and fill the notch between the summits. Three flanks plus their gaps do
   not fit across ~11px of content width. A filled silhouette of the same skyline was drawn to solve
   this.
2. **The silhouette read as anatomy, not mountains.** Two rounded summits either side of a central
   notch is an unfortunate shape at 16px, and no amount of proportion tuning fixed the underlying
   form.

Do not re-propose a two-lobed silhouette for this icon. If a visual tie to the church's mark is
wanted, pursue it somewhere the monoline has room to work — the app header or an about page — not a
16px favicon.

Other shapes tried and dropped in the song-book round, so they are not re-litigated: a stacked pair
of books (reads as a list/hamburger icon at 16px), a cover with a gold ribbon marker (the ribbon
merges into the cover and adds a third colour for no gain), a cover with a spine stripe (the spine
crowds the note), an open book with a note above it (top-heavy, two competing elements), and a plain
open book (clean, but carries no musical cue).

## Deployment

Assets are static files served from `src/worship_catalog/web/static/`, so they ship with the image —
no separate deploy step beyond the normal `docs/pi-deploy.md` flow. Browsers cache favicons
aggressively; expect to hard-refresh to see the change on a host that has already cached the 404.
