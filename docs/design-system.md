# ServeFlow design system

One set of tokens and components drives all three experiences: the **customer marketplace** (`frontend/customer/`), the **restaurant workspace**
(`frontend/restaurant-dashboard/`) and the private **Owner Control Centre** (`frontend/owner-control-centre/`). The marketing pages (`index.html`, `pricing/`) use the same tokens.

See it live: open `frontend/shared/design-system.html` (colour, type, icons, buttons, forms, badges, cards, tables, dialogs, empty states).

## Two designs: classic now, premium later

ServeFlow ships with the **classic** (earlier) design. The **premium** design is finished and kept ready, so it can be switched on later, for example once the product has proven itself with real users.
Both live in `frontend/shared/css/themes/<name>/` and share all markup, scripts, icons and the order animation, so switching changes the look only.

```
python tools/set_theme.py              # which design is active
python tools/set_theme.py premium      # switch to the premium design
python tools/set_theme.py classic      # switch back
```

The script copies the chosen design over the live stylesheets (no build step, no extra requests; pages load the same files as before). Edit a design in its own folder, then run the script again.
Tests fail if the live files drift from the active design, or if either design can no longer style the shared markup. The rest of this page describes the **premium** tokens; classic keeps its original tokens.

## Why this is not a Next.js / Tailwind rewrite

The brief asked for the look of a modern SaaS product, and for the Django backend and every working feature to stay. The frontend is a set of plain HTML pages with small
JavaScript modules and no build step, served as static files next to Django. Rebuilding it in Next.js would mean a new build and deploy pipeline, a rewrite of about 10,000
lines that already work (and the offline app, install message and push alerts that depend on static files), and a second runtime to host. None of that is needed to reach the
visual quality: the quality comes from tokens, type, spacing and consistent components, which are all CSS. So the system is built as CSS design tokens and shared components
that work the same in any stack, and a later move to Next.js and Tailwind would reuse them (the tokens map one-to-one to a Tailwind theme).

## Tokens (`frontend/shared/css/tokens.css`)

| Group | Values |
|---|---|
| Brand | Primary `#064E3B` (`--brand-900`), Dark `#022C22` (`--brand-950`), Mint `#86EFAC` (`--brand-300`), plus a green scale for tints |
| Neutrals | Background `#F8FAF9`, Surface `#FFFFFF`, Text `#1F2937`, secondary text, hairlines |
| Semantic | success, warning, danger, info (soft background + readable text), used only for status and alerts |
| Type | Geist (application), Plus Jakarta Sans (customer-facing headings), Geist Mono (order references). Sizes 12, 13, 15, 17, 20, 24, 30. Weights 400, 500, 600. Headings use a slight negative tracking |
| Space | 4px base: 4, 8, 12, 16, 20, 24, 32, 40, 48 |
| Radius | 6, 10, 14, 18, pill |
| Elevation | `--shadow-1` (hairline lift), `--shadow-2` (hover), `--shadow-pop` (menus, dialogs). Quiet and green-tinted |
| Motion | 120ms and 200ms, one easing curve, switched off for people who ask for reduced motion |
| Controls | 40px tall on desktop, 44px on touch screens (`pointer: coarse`); inputs are 16px on touch so phones don't zoom |

Old token names (`--ink`, `--accent`, `--surface-sunken` ...) still work. New code should use the brand and semantic names above.

## Fonts

Geist and Plus Jakarta Sans are self-hosted, not loaded from Google at run time, so they also work in the installed app offline. Run this once (it needs internet):

```
python tools/fetch_fonts.py
```

It downloads the files into `frontend/shared/fonts/` and writes `frontend/shared/css/fonts.css`. Until it has been run, pages use the device's own system font and nothing breaks.
Every page links `fonts.css` before `tokens.css`; a test enforces that.

## Icons

One sprite, `frontend/shared/assets/icons.svg`, in Lucide geometry (24px grid, 1.75 stroke, round caps), used as `icon("name")` in scripts or `<use href="...#i-name">` in HTML.
To add an icon, copy its paths from lucide.dev into the sprite as `<symbol id="i-name" viewBox="0 0 24 24">`. A test fails if any page or script asks for an icon that isn't in the sprite.

## Components (`frontend/shared/css/components.css`, `layout.css`)

Buttons (primary, secondary, ghost, danger, mint; small, icon, block, busy), inputs, selects, textareas, choice cards, cards (static and interactive), badges and status indicators,
category chips, segmented controls, steppers, food cards, alerts, empty states, skeletons, toasts, dialogs (a bottom sheet on phones), menus, tables, the install message, the live indicator.

**Tables** become stacked cards on phones. Give the table `class="table table--stack"` and each cell `data-label="Column name"`; the owner list pages and the team page already do.

## Navigation, one pattern per experience

* **Customer:** a light top bar. The brand on the left; on the right a single **Menu** (Menu, About, Track order, All restaurants, Sign in or My orders, Install) and the cart. Wide screens show the links inline.
* **Restaurant workspace:** a sidebar on desktop (restaurant name and role at the top, then Overview, Orders, Menu, Reviews, Team, Billing, Settings). On phones: four bottom tabs (Overview, Orders, Menu, **More**), where More opens a sheet with the rest and Account.
* **Owner Control Centre:** a dark sidebar on desktop, a slide-in drawer on phones, so the private admin area is never mistaken for a restaurant's workspace.

## Checking your changes

`python tools/visual_check.py` opens the real pages in a headless browser (Chromium via Playwright) with sample data at 320, 390, 768 and 1280px, writes screenshots to `tools/visual_out/`
and fails if any page is wider than the screen or throws a script error. It also opens each phone menu. The sample data lives only in that file; nothing fake ships in the product.
Setup: `pip install playwright && playwright install chromium`. The script stands in Inter for Geist until the real fonts are fetched.

`cd frontend && node --test` runs the unit and page tests, including the design-system guards (brand colours, font stack, icon sprite).
