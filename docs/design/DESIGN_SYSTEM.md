# LLM Arena — Design System ("Arena dark")

Source of truth for the look of the web UI. The implementation is three
stylesheets, loaded in this order by `src/web/templates/base.html`:

| File | Holds | Rule |
|---|---|---|
| `static/css/tokens.css` | Every colour, size, space, radius, duration, z-index — both themes | The only file that contains raw values |
| `static/css/base.css` | Reset, typography, app shell, layout helpers, utilities, breakpoints | Uses tokens only |
| `static/css/components.css` | Buttons, forms, badges, tables, tabs, alerts, modal, progress, page patterns | Uses tokens only |

No CSS framework, no build step. The only vendored JS is `htmx.min.js`; the
theme toggle and small behaviours live in `static/js/app.js`.

> Replaces the v0.2 document (glassy panels, radial gradients, `app.css`).
> That version is in git history; `static/css/app.css` is no longer linked.

---

## 1. Principles

1. **A dense tool, not a landing page.** Tables, badges and stat rows beat
   hero sections. Dark by default, calm, one accent.
2. **One accent.** Blue marks the primary action and *live* state, nothing
   else. Success / warning / danger are reserved for status.
3. **State is never colour alone.** Every status badge is dot + colour + word.
   "Not yet started" states (draft, queued, cancelled, approved-but-unlocked)
   use a hollow dot, "active" states a filled dot, `running` a pulsing dot.
4. **Separation by borders and background steps, not shadows.** Hairline
   1 px borders; surfaces step `bg → surface-1 → surface-2 → surface-3`.
5. **Motion only means "live".** The sole animation is the pulsing dot / accent
   bar on running work. `prefers-reduced-motion` switches it off.
6. **Small, strict scale.** Six font sizes, a 4 px spacing grid, radius never
   above 6 px.
7. **No raw values outside `tokens.css`.** If a value is needed twice, it is a
   token.

---

## 2. Tokens

### 2.1 Colour (both themes)

Theme is set by `data-theme="dark|light"` on `<html>`. A boot script in
`base.html` applies the saved choice (`localStorage["inno_theme"]`), else the
system preference, else dark, before first paint. The light theme is designed
separately (not an inversion): lower-chroma status colours, darker accent.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--c-bg` | `#0D0F12` | `#F3F4F6` | Page background |
| `--c-surface-1` | `#13161A` | `#FFFFFF` | Cards, sidebar, table body |
| `--c-surface-2` | `#191D22` | `#F7F8FA` | Inputs, secondary buttons, hover |
| `--c-surface-3` | `#20252B` | `#ECEEF1` | Active nav item, table header, pressed |
| `--c-border` | `#262B32` | `#DDE0E5` | Hairlines, dividers |
| `--c-border-strong` | `#353B44` | `#C5CAD2` | Control outlines |
| `--c-text` | `#E6E8EB` | `#14171C` | Body and headings |
| `--c-text-muted` | `#9AA3AE` | `#4F5864` | Secondary text, labels, meta |
| `--c-text-faint` | `#6E7782` | `#8A93A0` | **Disabled / decorative only** |
| `--c-accent` | `#4DA3FF` | `#0B63CE` | Primary button, focus ring, live bar |
| `--c-accent-hover` / `-active` | `#6BB3FF` / `#3A92EE` | `#0A56B3` / `#084A9A` | Primary button states |
| `--c-accent-text` | `#4DA3FF` | `#0B5CBF` | Links and accent-coloured text |
| `--c-accent-soft` | `#12263B` | `#E3EEFB` | Running badge fill, selection |
| `--c-on-accent` | `#07111C` | `#FFFFFF` | Text on the accent |
| `--c-success` (+`-bg`, `-border`) | `#3FB97F` | `#077A4C` | done / locked / approved |
| `--c-warning` (+`-bg`, `-border`) | `#D9A441` | `#955800` | in review |
| `--c-danger` (+`-bg`, `-border`) | `#F0616D` | `#C42B3B` | error, destructive |
| `--c-cat-c/e/m/a/n/x` | see file | see file | Question-category tints by QID prefix (chemistry, emotions, math, 3D, no-knowledge, contradiction) |
| `--c-on-cat` | `#0D0F12` | `#FFFFFF` | Text on a category tint |
| `--c-scrim` | `rgba(5,6,8,.72)` | `rgba(15,17,21,.45)` | Modal backdrop |

### 2.2 Contrast (computed from the values above, WCAG 2.x relative luminance)

All text pairs meet 4.5:1 (AA, normal text) in both themes.

| Pair | Dark | Light |
|---|---|---|
| text on bg | 15.63 | 16.32 |
| text on surface-1 | 14.78 | 17.96 |
| text on surface-3 | 12.57 | 15.45 |
| text-muted on bg | 7.52 | 6.55 |
| text-muted on surface-1 | 7.11 | 7.21 |
| text-muted on surface-3 | 6.04 | 6.20 |
| accent-text on bg / surface-1 | 7.31 / 6.91 | 5.79 / 6.37 |
| on-accent on accent / accent-hover | 7.23 / 8.61 | 5.69 / 7.01 |
| success on success-bg | 6.42 | 4.72 |
| warning on warning-bg | 7.05 | 5.09 |
| danger on danger-bg | 5.38 | 4.69 |
| on-cat on cat-c … cat-x | 7.54 – 10.58 | 4.63 – 5.72 |

Known limits, stated plainly:

- **`--c-text-faint` fails AA** (4.00 dark, 3.11 light on surface-1). That is
  why it is restricted to disabled controls and decoration and must never
  carry information.
- **Control borders are below 3:1** (`--c-border-strong` on surface-1 is 1.61
  dark, 1.65 light), so WCAG 1.4.11 (non-text contrast) is not met for input
  outlines. Inputs are still identified by label, position and the 2 px accent
  focus ring (6.9:1 / 5.7:1). Darkening the outline is a candidate follow-up.

### 2.3 Typography

One sans, one mono. Mono (`.mono`, `code`, `.num`) is for ids, scores and
anything that must align; numbers use tabular figures.

| Token | Size | Use |
|---|---|---|
| `--t-xs` | 11 px | Badges, table headers, section labels (uppercase, `--tracking-caps`) |
| `--t-sm` | 12 px | Secondary text, meta, code |
| `--t-md` | 13 px | Tables, controls, dense body |
| `--t-base` | 14 px | Default body |
| `--t-lg` | 16 px | Section titles (`h2`) |
| `--t-xl` | 22 px | Page titles (`h1`) |

Weights: `--w-regular` 400, `--w-medium` 500, `--w-semibold` 600. Line heights
`--lh-tight` 1.25 / `--lh-base` 1.5. Fonts: `--font-sans` (system stack),
`--font-mono` (JetBrains Mono → system mono).

### 2.4 Spacing, shape, sizing

- **Spacing** (4 px grid): `--s-1` 4 · `--s-2` 8 · `--s-3` 12 · `--s-4` 16 ·
  `--s-5` 20 · `--s-6` 24 · `--s-8` 32 · `--s-10` 40 · `--s-12` 48.
- **Radius**: `--r-1` 2 · `--r-2` 4 · `--r-3` 6 (maximum anywhere).
- **Borders**: `--bw` 1 px hairline, `--bw-bar` 2 px for active-state bars and
  hollow status dots.
- **Controls**: `--h-control` 32, `--h-control-sm` 24, `--h-row` 36,
  `--h-topbar` 48.
- **Layout widths**: `--w-sidebar` 224, `--w-content` 1440 max, `--w-aside`
  320, `--w-modal` 520 / `--w-modal-lg` 720, `--w-auth` 360, `--w-form` 720.
  Component widths (`--w-progress`, `--w-status`, `--w-field-*`, `--h-picker`,
  `--h-pre`, …) are also tokens so no component hard-codes a pixel size.
- **Icons**: `--icon` 16 px, `--icon-stroke` 1.5, line style, `currentColor`.
- **Layers**: `--z-sticky` 10, `--z-modal` 200, `--z-toast` 300.
- **Motion**: `--dur-1` 100 ms, `--dur-2` 160 ms, `--dur-live` 1600 ms,
  `--ease` `cubic-bezier(.2,0,0,1)`.

Dynamic values that cannot be a token (leaderboard bar widths computed in JS)
are passed through one custom property, `--w`, set inline and consumed by
`width: var(--w)`.

---

## 3. App shell

```
┌───────────┬──────────────────────────────────────────────┐
│ LLM Arena │ Workspace / Runs                       [☼/☾] │  topbar, 48 px
│           ├──────────────────────────────────────────────┤
│ Dashboard │                                              │
│ Question  │  page-header: title (h1) + one primary action│
│  sets     │                                              │
│ Runs      │  content, max 1440 px                        │
│ Leaderb.  │                                              │
│ Admin*    │                                              │
│ ───────── │                                              │
│ user ROLE │                                              │
│ Account · │                                              │
│ Log out   │                                              │
└───────────┴──────────────────────────────────────────────┘
   224 px                    * admins only
```

- Markup: `base.html` (shell, skip link, topbar, theme toggle, toast region) and
  `components/_sidebar.html`.
- The active nav item is chosen by `{% set active_tab = '…' %}` in the page
  template (`home`, `questions`, `runs`, `results`, `admin`) and shown with a
  2 px left bar and `surface-3` fill.
- The breadcrumb in the topbar is a `{% block crumbs scoped %}` (needs `scoped`
  to read `section_labels` from the shell). Pages may override it.
- Logged-out pages (`login`, `register`) use `.shell.no-sidebar`.
- Breakpoints (literal values, since CSS cannot use variables in `@media`):
  **1100 px** stacks two-column pages and drops `grid-3` to two columns,
  **860 px** turns the sidebar into a top strip, **640 px** stacks the diff and
  compare panels and `grid-2/3`. Tables scroll inside `.table-scroll`; the page
  itself does not scroll sideways (checked at 390 px).

---

## 4. Components

Class names are the original vocabulary on purpose: templates, HTMX targets and
`app.js` select on them, so the redesign changed the CSS and the markup around
them without touching any `hx-*` attribute.

| Component | Classes | Use it for |
|---|---|---|
| Button | `.btn`, `-primary`, `-secondary`, `-ghost`, `-danger`, `-sm`, `-lg`, `-icon`, `-block` | One `-primary` per page header. `-danger` only for destructive actions. `-ghost` for toolbar and icon buttons |
| Form | `.field`, `.form-field`, `.form-row`, `.form-inline`, `.input`, `.select`, `.textarea`, `.has-error` | Labels above inputs; errors under the field with the danger colour **and** text |
| Select list | `.select.model-picker` | The multi-select model picker (native `<select multiple>`; option text is reset so group labels stay uppercase and options do not) |
| Badge | `.badge`, `-draft`, `-review`, `-approved`, `-locked`, `-done`, `-queued`, `-running`, `-cancelled`, `-error`, `-role-admin/-author/-reviewer` | Status of a question set or run. Always contains `.dot` + label text |
| Chip / pill | `.chip`, `.chips`, `.pill`, `.kbd` | Filters, model ids, keyboard hints |
| Card / stat | `.card`, `.card-header`, `.stat`, `.stat-row`, `.stat-label`, `.stat-value`, `.metric`, `.kv` | Grouped content; headline numbers |
| Table | `.table`, `.table-wrap`, `.table-scroll`, `th.num` / `td.num`, `.sort-indicator` | Dense lists. Numbers right-aligned, mono, tabular. Header is `--t-xs` uppercase |
| Progress | `.progress`, `.bar`, `.bar-fill`, `.is-live`, `.model-row`, `.model-progress`, `.m-name`, `.m-pct` | Run progress; per-model rows share one column grid so bars align |
| Tabs | `.tabs`, `.tab` | Section switching within a page |
| Alerts / toasts | `.alert`, `-info/-success/-warn/-error`, `.toast`, `.toast-region`, `.flash-stack` | Feedback. Icon + title + text; never colour alone |
| Modal | `.modal-backdrop`, `.modal`, `-header/-body/-footer/-close` | New-run dialog; `app.js` moves focus to the first field on open (it does not restore focus on close) |
| Empty state | `.empty` (partial `components/_empty_state.html`) | Text only plus one secondary action — no illustrations |
| Pagination | `.pagination` (partial `components/_pagination.html`) | "Previous / Next" |
| Page patterns | `.page-header`, `.toolbar`, `.steps` / `.step`, `.dropzone`, `.q-list` / `.q-item` / `.q-choice`, `.validation-list`, `.diff`, `.compare`, `.answer-*`, `.output-block`, `.auth-*` | Question import, review, version diff, leaderboard compare cards, per-question answers, raw model output, login |

### Status vocabulary

| State | Badge | Dot |
|---|---|---|
| draft, queued, cancelled | neutral | hollow |
| in review | warning | filled |
| approved | success | hollow (approved, not locked) |
| locked, done | success | filled |
| running | accent | **pulsing** (only animated element) |
| error | danger | filled |

### Interaction

- One focus style everywhere: 2 px accent outline, 2 px offset (`:focus-visible`).
- `skip-link` jumps to `#main`.
- Theme toggle: `[data-theme-toggle]` in the topbar; shows the icon of the
  theme you would switch to; has an `aria-label`.
- The only stored preference is `inno_theme` in `localStorage` (reads and
  writes are wrapped in `try/catch`).

---

## 5. Adding or changing UI

1. Need a new colour, size or duration? Add a token to `tokens.css` (both
   themes for colours) and use it. Do not write a raw value in the other files.
2. Reuse a component class before inventing one. If you add one, put it in the
   matching section of `components.css`.
3. Never remove or rename a class or `id` that an `hx-target`, `hx-include`,
   `hx-swap` or `app.js` refers to. Check with `grep -rn` first.
4. A new status needs dot + colour + word, and an entry in the table above.
5. Check both themes and a 390 px viewport. Run `pytest -q`; the template smoke
   tests render every page.

## 6. Known gaps

- Native `<select multiple>` and `<input type="date">` can only be partly
  styled; they follow the theme but keep browser chrome.
- Sort indicators in table headers remain text arrows because `app.js` swaps
  them.
- Control outlines are below 3:1 (see 2.2).
- `docs/design/mockups/*.png` are screenshots of the **old** design and are
  kept only for history.
