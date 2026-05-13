# Inno LLM Scoring — Design System

_Version 0.2 · Day-1 of the 5-day GUI rewrite · author: UI design worker_

This document describes the visual & interaction system used by the rewritten
web UI. It is the source of truth for the tokens, components, and patterns
implemented in `static/css/app.css` and the Jinja2 templates under
`templates/`.

The visual language is **inherited from the existing leaderboard renderer**
(`src/web/leaderboard.py`), then extended into a complete app shell. We kept:

- Dark-by-default theme with a `data-theme="light"` override.
- Glassy panels (`color-mix(in oklab, var(--panel) 92%, transparent)` +
  `backdrop-filter: blur(10px)`).
- Radial accent gradients on the background (blue / green / amber).
- Sticky toolbar pattern, score dots, comparison cards, and the leaderboard
  table.

> **No CSS framework dependency.** Vanilla CSS only. Vanilla JS only.
> The only vendored JS dependency is `htmx.min.js` (v1.9.12, ~48 KB).
> The Dockerfile copies these files straight in — no build step.

---

## 1. Design principles

1. **Information-dense but breathable.** This is a daily tool. Tables, badges
   and stat cards beat hero sections.
2. **Status legibility at a glance.** Color-coded badges everywhere a workflow
   state matters (`draft / in_review / approved / locked` for sets,
   `queued / running / done / error` for runs).
3. **One primary action per page.** The user should always know what the
   next step is — there is at most one `btn-primary` per page header.
4. **Keyboard-friendly.** Visible focus rings, sensible tab order, `Escape`
   closes modals, password fields autocomplete correctly.
5. **Dark mode by default**, light toggle persists via `localStorage` under
   the key `inno_theme`.
6. **Progressive enhancement via HTMX.** Forms still work without JS where
   it matters. HTMX is layered on for the interactive bits.

---

## 2. Tokens

All tokens are CSS custom properties on `:root`, overridden under
`[data-theme="light"]`. See `static/css/app.css §1 Tokens` for the full list.

### 2.1 Color

| Token              | Dark value              | Light value           | Use                                  |
| ------------------ | ----------------------- | --------------------- | ------------------------------------ |
| `--bg`             | `#0b1020`               | `#f7f8fb`             | Page background                      |
| `--panel`          | `rgba(255,255,255,.06)` | `#ffffff`             | Card / panel surface                 |
| `--panel-2`        | `rgba(255,255,255,.08)` | `#ffffff`             | Slightly elevated surface            |
| `--text`           | `rgba(255,255,255,.92)` | `#0f172a`             | Primary text                         |
| `--muted`          | `rgba(255,255,255,.62)` | `#556070`             | Secondary text / labels              |
| `--border`         | `rgba(255,255,255,.12)` | `rgba(15,23,42,.12)`  | Hairlines                            |
| `--accent`         | `#60a5fa`               | `#2563eb`             | Primary action / links               |
| `--accent-2`       | `#a78bfa`               | `#7c3aed`             | Gradient pair / brand mark           |
| `--good`           | `#22c55e`               | `#16a34a`             | Success, positive scores             |
| `--bad`            | `#f87171`               | `#dc2626`             | Error, wrong answers                 |
| `--warn`           | `#fbbf24`               | `#b45309`             | Pending review                       |
| `--info`           | `#38bdf8`               | `#0284c7`             | Info, chemistry category             |

#### Semantic status palette

Workflow + run statuses use dedicated tokens so badges and progress bars stay
in sync if we re-skin later:

| Token                | Maps to       | Use                       |
| -------------------- | ------------- | ------------------------- |
| `--status-draft`     | slate / muted | Set status `draft`        |
| `--status-review`    | warn          | Set status `in_review`    |
| `--status-approved`  | accent        | Set status `approved`     |
| `--status-locked`    | good          | Set status `locked`       |
| `--status-queued`    | slate / muted | Run status `queued`       |
| `--status-running`   | accent        | Run status `running` (pulsing dot) |
| `--status-done`      | good          | Run status `done`         |
| `--status-error`     | bad           | Run status `error`        |

#### Category palette (QID prefix → color)

| Prefix | Name          | Token         |
| ------ | ------------- | ------------- |
| `C`    | chemistry     | `--info`      |
| `E`    | emotions      | `--accent-2`  |
| `M`    | math          | `--good`      |
| `A`    | reasoning3d   | `--warn`      |
| `N`    | no_knowledge  | `--muted`     |
| `X`    | contradiction | `--bad`       |

### 2.2 Typography

| Token        | Value                                                       |
| ------------ | ----------------------------------------------------------- |
| `--font-sans`| `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, ...` |
| `--font-mono`| `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, ...`       |

Scale:

| Token       | Size | Use                              |
| ----------- | ---- | -------------------------------- |
| `--fs-xs`   | 11px | Badges, table headers (uppercase) |
| `--fs-sm`   | 12px | Helper text, captions             |
| `--fs-md`   | 13px | Table body, secondary controls    |
| `--fs-base` | 14px | Default body                      |
| `--fs-lg`   | 16px | Section titles                    |
| `--fs-xl`   | 20px | Card titles                       |
| `--fs-2xl`  | 26px | Auth-card heading                 |
| `--fs-3xl`  | 34px | Page title (`h1`)                 |

Weights used: `500 / 600 / 700 / 750`. Letter-spacing is tightened slightly
for headings (`-0.02em` ... `-0.03em`).

### 2.3 Spacing

4-pixel grid: `--space-1` = 4px, `--space-2` = 8px, … `--space-10` = 72px.
All component padding/gap values come from this scale.

### 2.4 Radii

| Token             | Value | Use                           |
| ----------------- | ----- | ----------------------------- |
| `--radius-sm`     | 8px   | Small chips, inline kbd       |
| `--radius`        | 14px  | Buttons, inputs, chips        |
| `--radius-lg`     | 16px  | Cards, table wraps            |
| `--radius-xl`     | 22px  | Modals, auth card             |
| `--radius-pill`   | 999px | Badges, score dots, progress  |

### 2.5 Shadows & ring

| Token            | Value                                       | Use            |
| ---------------- | ------------------------------------------- | -------------- |
| `--shadow`       | `0 14px 30px rgba(0,0,0,.28)` (dark)        | Cards          |
| `--shadow-2`     | `0 10px 22px rgba(0,0,0,.22)` (dark)        | Toolbar, alerts|
| `--shadow-pop`   | `0 20px 40px rgba(0,0,0,.38)` (dark)        | Modal, toast   |
| `--ring`         | `0 0 0 3px rgba(96,165,250,.35)`            | Focus ring     |

### 2.6 Motion

| Token          | Value                                |
| -------------- | ------------------------------------ |
| `--transition` | `140ms cubic-bezier(.2,.7,.2,1)`     |

Custom animations defined: `pulse` (running badge dot), `fade-in`, `pop-in`,
`slide-in` (toast), `indeterminate` (progress bar), `shimmer` (skeletons).
All animations short-circuit under `prefers-reduced-motion: reduce`.

### 2.7 Layout

| Token           | Value   | Use                  |
| --------------- | ------- | -------------------- |
| `--container`   | 1240px  | Max content width    |
| `--nav-height`  | 60px    | Sticky nav offset    |

---

## 3. Responsive breakpoints

We use very few breakpoints because most layouts are CSS-Grid based and adapt
intrinsically. Hard breakpoints:

| Breakpoint  | Effect                                                       |
| ----------- | ------------------------------------------------------------ |
| ≤ 980 px    | Two-column grids (`.grid-2`, `.grid-content`, `.grid-sidebar`) collapse to a single column. |
| ≤ 800 px    | Diff view collapses to single column.                        |
| ≤ 720 px    | Run model rows collapse to single column.                    |
| ≤ 640 px    | Compare cards stack vertically.                              |

There is no separate mobile breakpoint for the nav — the user-badge dropdown
remains usable at narrow widths, just visually tighter.

---

## 4. Layout primitives

| Class             | What it does                                              |
| ----------------- | --------------------------------------------------------- |
| `.container`      | `max-width: 1240px` + 20px gutter, centered.              |
| `.page`           | Vertical padding for main content area.                   |
| `.page-header`    | Flex row with title + actions, wraps on narrow screens.   |
| `.row`            | Flex row, wraps, gap = 12 px.                             |
| `.row-tight`      | Flex row, wraps, gap = 8 px.                              |
| `.stack`          | Flex column, gap = 12 px.                                 |
| `.stack-tight`    | Flex column, gap = 8 px.                                  |
| `.spread`         | Flex row, `justify-content: space-between`.               |
| `.grid`           | CSS grid with gap = 16 px.                                |
| `.grid-2`         | Two equal columns.                                        |
| `.grid-3` `.grid-4` | Three / four equal columns.                             |
| `.grid-content`   | Asymmetric 1.2fr / 0.8fr (main + sidebar).                |
| `.grid-sidebar`   | Asymmetric 1.4fr / 0.6fr (denser sidebar).                |
| `.divider`        | 1 px hairline with vertical breathing room.               |

---

## 5. Components

> Specs are concise; the canonical source is `static/css/app.css`.

### 5.1 Button

| Class                | Notes                                            |
| -------------------- | ------------------------------------------------ |
| `.btn`               | Base: 14px text, 14px radius, hairline border.   |
| `.btn-primary`       | Gradient fill + glow, used for the one primary action per page. |
| `.btn-danger`        | Red gradient — confirm dangerous actions with `data-confirm`. |
| `.btn-success`       | Green gradient — rarely used; favor `.btn-primary`. |
| `.btn-ghost`         | Transparent background, used for Cancel / Back.  |
| `.btn-sm`, `.btn-lg` | Size modifiers.                                  |
| `.btn-block`         | Full width.                                      |
| `.btn-icon`          | Square icon button.                              |
| `.btn-group`         | Joined segmented buttons.                        |

### 5.2 Card

`.card` is the unit of content. Variants: `.card-tight` (smaller padding),
`.card-pad-lg` (luxurious padding), `.card.glass` (frosted), `.card-link`
(adds hover-translate for clickable cards in result galleries).

`.card-header` for the title row, `.card-footer` for action rows.

### 5.3 Form controls

| Class             | Notes                                              |
| ----------------- | -------------------------------------------------- |
| `.input` `.select` `.textarea` | Unified visual; focus uses `--ring`.   |
| `.form-field`     | Label + control + help/error stack.                |
| `.form-field.has-error` | Red border + error tint.                     |
| `.form-row`       | Two-column form fields, collapses < 640 px.        |
| `.field`          | Compact icon-prefixed inline field (toolbar use).  |
| `.check` `.radio` | Custom checkbox/radio matching brand accent.       |
| `.switch`         | Toggle switch for binary settings (used in run model preset). |
| `.pw-strength`    | 4-segment strength meter, fed by JS (`data-pw-strength-for`). |

### 5.4 Table

`.table` + wrapper `.table-wrap` (rounded corners, shadow). Sortable variant:
add `class="sortable"` and `data-sort="string|number|date"` to each header.
The leaderboard table uses its own render path (full client-side, in
`templates/results/leaderboard.html`) for snappy sort/compare.

Visual touches:

- Sticky header with blur.
- Zebra rows + hover tint via `color-mix`.
- Numeric columns use `font-variant-numeric: tabular-nums`.
- `.table.compact` shrinks paddings for audit logs etc.
- `tr.sel` highlights selected rows (compare panel).

### 5.5 Badge

| Class                  | Status                |
| ---------------------- | --------------------- |
| `.badge-draft`         | Set draft             |
| `.badge-review`        | Set in_review         |
| `.badge-approved`      | Set approved          |
| `.badge-locked`        | Set locked            |
| `.badge-queued`        | Run queued            |
| `.badge-running`       | Run running (pulsing) |
| `.badge-done`          | Run done              |
| `.badge-error`         | Run error             |
| `.badge-role-admin`    | User role             |
| `.badge-role-author`   | User role             |
| `.badge-role-reviewer` | User role             |
| `.cat-{C,E,M,A,N,X}`   | Category chip         |

Use the partial `templates/components/_status_badge.html` to render a
status — it includes the colored dot and label automatically.

### 5.6 Chip

`.chip` is a passive pill (for filter chips, count chips, comparison
indicators). `.chip.interactive` adds hover & cursor. `.chip.active` is the
selected state in filter rows.

### 5.7 Alert / Flash / Toast

| Class                | Notes                                          |
| -------------------- | ---------------------------------------------- |
| `.alert-success`     | Green                                          |
| `.alert-error`       | Red                                            |
| `.alert-warn`        | Amber                                          |
| `.alert-info`        | Blue                                           |
| `.flash-stack`       | Sticky region at the top of the page for flashes — included by `base.html`. |
| `.toast-region`      | Fixed bottom-right. Use `window.toast(msg, kind)` in JS. |
| `.alert[data-auto-dismiss="ms"]` | Auto-fades after the given ms.     |

### 5.8 Modal

A modal is a `.modal-backdrop` + `.modal` pair. Open via
`<button data-modal-target="#id">`. Close via `data-modal-close` on any
element, click outside, or `Escape`. The "New run" modal in
`templates/runs/new.html` is the reference implementation.

### 5.9 Progress

`.progress > .bar-fill` with inline `width: N%`. Add `.indeterminate` for an
animated bar without known progress.

### 5.10 Steps

`.steps > .step` (with `.active` / `.done`) is the multi-step indicator used
by the import flow.

### 5.11 KBD / Code

`.kbd` is a small pill that wraps mono text — used for IDs, shortcuts, and
status hints. Inline `code.text-mono` is preferred for IDs longer than ~12 chars.

### 5.12 Dropzone

`.dropzone` with `data-dropzone` attribute is the drag-and-drop file picker
used in the question import flow. `static/js/app.js` wires the dragover
state and triggers a `change` event on the hidden file input.

### 5.13 Diff view

`.diff > .diff-pane > .diff-line` (`.add | .del | .ctx`). Used in
`templates/questions/diff.html`. Server pre-computes per-line annotation;
the CSS only colors them.

### 5.14 Validation list

`.validation-list li.v-pass | .v-warn | .v-fail` — used in two places:
the import preview and the side panel on the question-set detail page. The
detail-page panel auto-refreshes every 30 s via HTMX (`hx-trigger="every 30s"`)
plus whenever a `set:revalidated` event is broadcast on `body`.

### 5.15 Empty state

`templates/components/_empty_state.html` accepts:

- `empty_title`, `empty_body`
- `empty_cta_label`, `empty_cta_href`
- `empty_icon ∈ { 'inbox', 'flask', 'play', 'list' }`

### 5.16 Skeletons

`.skeleton` is a shimmering placeholder block. Use to fill space while HTMX
is loading content into a panel — but only where the latency is noticeable.

---

## 6. Interaction patterns (HTMX)

We use HTMX 1.9.12 (vendored at `static/js/htmx.min.js`, ~48 KB). Major
patterns:

| Goal                                              | Attributes                                                                                |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Live filter a table without reload                | `hx-get="..." hx-trigger="input changed delay:300ms" hx-target="#table" hx-select="#table"` |
| Modal-launched form (e.g. New run)                | `<button data-modal-target="#new-run-modal">` — no HTMX; the form posts normally and the server returns a redirect. |
| Live progress on run detail                       | `<div hx-get="/runs/{id}/fragment" hx-trigger="every 2s" hx-target="this" hx-select=".run-models" hx-swap="outerHTML">` |
| Inline status transition (Submit / Approve / Lock)| Plain HTML forms posting to action URLs; server returns redirect + sets HX-Trigger flash. |
| Live preview while editing a question             | `<form hx-post="..." hx-target="#preview-pane" hx-trigger="input changed delay:300ms from:find input">` |
| Validation revalidation                           | `hx-get="/sets/{id}/validate" hx-trigger="load, every 30s, set:revalidated from:body"`    |
| Toast from HTMX response                          | Server sets `HX-Trigger: { "flash": { "message": "...", "kind": "success" } }`; JS in `app.js` listens for the `flash` event on body. |

**Loading indicators.** Add `class="htmx-indicator"` to any element that
should fade in during an in-flight request. The class is wired by HTMX
automatically (`.htmx-request .htmx-indicator { opacity: 1 }`).

**Error handling.** `app.js` listens for `htmx:responseError` and
`htmx:sendError` and surfaces a toast — backend doesn't need to render error
HTML for those.

---

## 7. Accessibility

- All interactive elements are real `<button>` / `<a>` / `<input>` — no
  click-handlers on `<div>`s.
- Focus ring (`--ring`) is **always visible** under `:focus-visible`, never
  suppressed. We deliberately do NOT use `outline: none` without replacement.
- Modals use `role="dialog" aria-modal="true"` and trap focus on the first
  input. `Escape` closes them.
- Tab badges use `role="tab" aria-selected="true|false"`.
- Pulsing run-status badge avoids epilepsy concerns: amplitude is gentle,
  frequency under 3 Hz, and is fully suppressed under
  `prefers-reduced-motion: reduce`.
- Color is never the only signal. Status badges combine a dot, a color, and
  the status word. Score values combine a dot and a number.
- Forms use `autocomplete="username"`, `current-password`, `new-password`
  attributes correctly so password managers behave.
- Sortable tables expose the sort direction in the header text (` ↑ ` / ` ↓ `)
  alongside the color cue.

---

## 8. Theme handling

```js
// Applied before paint by base.html to avoid flash of wrong theme.
const saved = localStorage.getItem("inno_theme");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
document.documentElement.setAttribute("data-theme", saved || (prefersDark ? "dark" : "light"));
```

Any element with `[data-theme-toggle]` flips and persists the theme. Labels
that should reflect the active theme should carry `data-theme-label`.

Storage key: `inno_theme`. Old key from the static leaderboard was
`lb_theme` — we deliberately migrated to avoid leaking state from the
embedded static dashboard.

---

## 9. File map

```
static/
├── css/
│   └── app.css                    # design tokens + components + utilities
├── js/
│   ├── app.js                     # vanilla JS for theme, modals, drops, etc.
│   └── htmx.min.js                # vendored HTMX 1.9.12
└── img/
    └── favicon.svg                # brand mark

templates/
├── base.html                      # app shell (nav + flash + footer)
├── components/
│   ├── _flash.html
│   ├── _nav.html
│   ├── _user_badge.html
│   ├── _status_badge.html
│   ├── _pagination.html
│   └── _empty_state.html
├── auth/
│   ├── login.html
│   ├── signup.html
│   ├── forgot_password.html
│   └── reset_password.html
├── questions/
│   ├── list.html
│   ├── import.html
│   ├── detail.html
│   ├── edit.html
│   └── diff.html
├── runs/
│   ├── list.html
│   ├── new.html                   # modal partial + optional standalone page
│   └── detail.html
├── results/
│   ├── list.html
│   └── leaderboard.html
└── errors/
    ├── 404.html
    └── 500.html

docs/design/
├── DESIGN_SYSTEM.md               # this file
└── mockups/                       # hero mockups (optional — see §11)
```

---

## 10. Required context the backend should provide

Templates expect these names in the Jinja context:

- `current_user` — `None` when logged out, otherwise an object with
  `.username`, `.email`, `.role ∈ {admin, author, reviewer}`.
- `flashes` — iterable of `{category, message[, title]}` (categories:
  `success | error | warn | info`).
- `csrf_token()` callable — returns a CSRF token (or empty string if you
  don't use CSRF; templates degrade gracefully).
- `request` — Flask/FastAPI request object, used only for `request.args`.
- A `url_for(endpoint, **kw)` callable matching Flask conventions. The
  endpoints referenced (so far) are:
  - `home`
  - `login`, `logout`, `signup`, `forgot_password`, `reset_password`, `account`
  - `questions.list`, `questions.import_view`, `questions.preview`,
    `questions.detail`, `questions.edit`, `questions.edit_one`,
    `questions.diff`, `questions.validate`, `questions.submit_review`,
    `questions.approve`, `questions.lock`
  - `runs.list`, `runs.new`, `runs.create`, `runs.detail`,
    `runs.detail_fragment`, `runs.cancel`
  - `results.list`, `results.leaderboard`, `results.export`,
    `results.run_csv`, `results.run_json`
  - `static`

Page-specific data shapes are documented inline at the top of each template
as a Jinja `{# … #}` comment.

---

## 11. Hero mockups

Three flagship-screen mockups live under `docs/design/mockups/`:

| Screen           | File                                                         | Notes                                                                                                          |
| ---------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| Login            | `docs/design/mockups/login.png`                              | Matches token palette, gradient brand mark, primary CTA.                                                       |
| Questions list   | `docs/design/mockups/questions_list.png`                     | Filter chips with counts, color-coded status badges, info-dense table with sortable headers and "Open" actions. |
| Leaderboard      | `docs/design/mockups/leaderboard.png`                        | Sticky filter toolbar, compare chips, 4-model preset rows with score dots, side comparison cards.              |

Mockups were generated as vision-research aids. They are **representative**,
not pixel-perfect: the leaderboard mockup shows a slightly different brand
mark/name (model drift). The implemented templates are the source of truth.

---

## 12. Open design questions

Captured here so the parent (or a follow-up worker) can resolve quickly:

1. **Signup default.** Currently we render a "signup disabled" notice when
   `signup_enabled` is falsy. Decision needed: is signup enabled by default
   in dev? In prod? Stored where?
2. **Forgot-password mechanism.** The demo template displays the generated
   token directly on the success page (no real email infra). Acceptable for
   the school project? Or should we keep it but also gate it behind an admin
   "reveal" toggle?
3. **Run cancellation semantics.** UI exposes a cancel button while
   `queued / running`. Backend behavior (kill task vs mark cancelled) is not
   defined here.
4. **Per-run leaderboard data shape.** The template assumes the same row
   shape as `results/leaderboard/leaderboard.json` written by the current
   exporter (model_id, total, chemistry, emotions, math, reasoning3d,
   no_knowledge, contradiction, correct, wrong, blank, format_violations).
   If we change shape, this template needs an update.
5. **Audit log granularity.** We expose `(at, actor, action, detail)` — the
   level of detail is up to the backend.
6. **Account page.** Linked from the user-badge dropdown but not yet
   implemented as a template — left for a follow-up day.
7. **Role assignment UI.** Not part of this rewrite. Assume admin manages
   roles via CLI for now.
8. **Set-id vs slug.** We use `set_id` (already in the DB schema) as the
   URL slug. Future: human-readable slugs?

---

_End of DESIGN_SYSTEM.md_
