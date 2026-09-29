# Estate bar

The one top strip that links the Intent Solutions properties. It is identical on
every site that carries it: same links, order, labels, font and spacing. The only
thing a site may change is the accent color of the current-property link.

`INTENT SOLUTIONS · LABS · EVALS · DEMOS · LEARN · OMARCHY · TONS OF SKILLS`

This folder is the single source. Every other copy is vendored from here and
checked against `manifest.sha256`. Authority: `000-docs/088-AT-DSGN-estate-bar-amendment.md`.

## Files

| File | What it is |
|---|---|
| `links.json` | Labels, order, hrefs, and which sites carry the bar |
| `estate-bar.css` | Self-contained styles, px-sized, font included via `fonts/` |
| `fonts/JetBrainsMono-Medium.woff2` | Self-hosted JetBrains Mono (SIL OFL 1.1, see `fonts/OFL.txt`) |
| `fragments/estate-bar.<site>.html` | The rendered fragment for each carrier, with `aria-current` set |
| `manifest.sha256` | Hashes of everything above |
| `render.mjs` | Regenerates `fragments/` and the manifest from `links.json` |
| `check_estate_bar.py` | Stdlib checker each consumer runs in CI |

## Who carries it

`company` (intentsolutions.io), `labs`, `evals`, `demos`, `learn`, `omarchy`.
Tons of Skills is a destination in the bar but does not carry it; it has its own
design constitution.

## Changing the bar

1. Edit `links.json` or `estate-bar.css`, bump `version`, add a `CHANGELOG.md` entry.
2. `node estate-bar/render.mjs`
3. Merge here first, then re-sync each consumer. A consumer's CI fails until its
   vendored copy and its pages match.

Never edit a vendored copy in a consumer repo. The manifest check will fail it.

## Consuming it

Copy this folder's `estate-bar.css`, `fonts/`, `fragments/`, `manifest.sha256` and
`check_estate_bar.py` into the consumer (for example `vendor/estate-bar/`). Put
the fragment for your site as the first element in `<body>`, serve the CSS and
font from your own origin (Learn's content security policy blocks outside fonts),
then check the built HTML:

```bash
python3 vendor/estate-bar/check_estate_bar.py --site demos \
  --vendor vendor/estate-bar --glob 'site/**/*.html' --exempt 'site/clients/**'
```

Set the accent per site, nothing else:

```css
.is-estate-bar { --estate-accent: #e0613a; }
```

## Rules the markup and CSS encode

- The current property is marked with accent color **and** underline, never color alone.
- Links are 44px tall touch targets.
- On narrow screens the row scrolls sideways with a fade on the right edge. It never wraps.
- Sizes are px so the bar does not scale with a site's root font size.
- No JavaScript. No external requests.
