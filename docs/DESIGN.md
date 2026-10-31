# Design System — Vercel / Geist

Adopted from the spec at `/home/mukul/Downloads/vercel.md`.

> Note: line 60 of the source file contains a stray non-token string inside the
> `label-sm` weight value. It is ignored; `label-sm` is treated as **weight 500**.

## Why this system fits a security project

- **Monochrome ink-on-near-white.** No colour competes with status meaning.
- **CSP-friendly.** No CSS-in-JS, no external font CDN, no raster hero images —
  the mesh gradient is pure CSS. `style-src 'self'` and `font-src 'self'` hold.
- **Hairline structure.** Cards and tables read like an audit document.

## Tokens

Defined once in `frontend/src/index.css` under `@theme` and consumed as Tailwind
utilities (`bg-canvas`, `text-ink`, `rounded-pill`, `text-heading-lg`, …).

### Colour

| Token | Value | Use |
|---|---|---|
| `canvas` | `#fafafa` | Page background |
| `elevated` | `#ffffff` | Cards, inputs, buttons |
| `ink` | `#171717` | Headings, primary fills |
| `body` | `#4d4d4d` | Paragraphs, nav |
| `mute` | `#8f8f8f` | Captions, metadata |
| `faint` | `#a1a1a1` | Placeholders, disabled |
| `hairline` | `#ebebeb` | Every 1px border |
| `hairline-soft` | `#f2f2f2` | Inset wells |
| `link` | `#0070f3` | Links, focus, active dot |
| `error` | `#ee0000` | Destructive / validation |
| `warning` | `#f5a623` | Caution |
| `violet` / `cyan` / `pink` | accents | Illustration only |

Colour is **never** the sole carrier of meaning: status is a label plus a dot.

### Typography

Geist Sans, self-hosted via `@fontsource-variable/geist`. A single typeface is
used throughout; the project does not ship a monospace font.

| Utility | Size / line | Weight | Tracking |
|---|---|---|---|
| `text-display-xl` | 48 / 48 | 600 | −2.4px |
| `text-heading-lg` | 32 / 40 | 600 | −1.28px |
| `text-heading-md` | 20 / 28 | 600 | −0.4px |
| `text-label-sm` | 14 / 20 | 500 | −0.28px |
| `text-eyebrow` | 12 / 16 | 500 | 0 (uppercase) |
| `text-body-lg` | 16 / 24 | 400 | 0 |
| `text-body-md` | 14 / 20 | 400 | 0 |
| `text-body-sm` | 12 / 16 | 400 | 0 |
| `text-btn-lg` | 16 / 20 | 500 | 0 |
| `text-btn-md` | 14 / 20 | 500 | 0 |

### Radii & elevation

`sm` 6px (app buttons, inputs) · `md` 12px (cards) · `lg` 16px (large panels) ·
`pill-cat` 64px (category tabs) · `pill` 100px (marketing CTAs).

Depth is a hairline first; `shadow-whisper` for light lift and `shadow-float` for
menus and modals only.

### Spacing

4px base: 4 · 8 · 12 · 16 · 24 · 32 · 40 · 64 · 96 · 128.

## Shape by context

- **Marketing surface** (landing hero, auth CTA): black **pill**.
- **In-app chrome** (nav, bid, close, verify, logout): tight **6px square**.

Mixing these in one context is a design error.

## Component mapping

| Geist component | Implementation |
|---|---|
| `nav-bar` | `components/AppShell.tsx` |
| `button-primary` / `button-secondary` | `Button` variant `primary` / `secondary` |
| `button-primary-sm` / `button-ghost-sm` | `Button` variant `primary-sm` / `ghost-sm` |
| `text-input` | `components/ui/Input.tsx` |
| `feature-card` / `pricing-card` | `components/ui/Card.tsx` |
| `code-block` | `rounded-md border border-hairline bg-elevated p-4 text-body-sm` |
| `button-category-pill` | admin tabs and auction filters |
| `hero-band` + mesh | `Landing` page, `.mesh-gradient` |

## Accessibility

- `body` (#4d4d4d) on canvas ≈ **7.5:1** — passes AA/AAA for body text.
- `mute` (#8f8f8f) on canvas ≈ **3.1:1** — captions and metadata only, never
  body copy.
- `faint` (#a1a1a1) — placeholders and disabled states only.
- Focus is always visible via a 2px `link` outline.
- `prefers-reduced-motion` disables the live pulse and transitions.

## Constraints

- No dark mode: the source system defines none.
- No second decorative system: the mesh gradient is the only flourish.
- No CSS-in-JS: runtime style injection would force `unsafe-inline` into the CSP.