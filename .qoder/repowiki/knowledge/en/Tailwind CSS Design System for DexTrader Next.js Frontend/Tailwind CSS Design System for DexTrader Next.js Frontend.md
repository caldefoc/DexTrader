---
kind: frontend_style
name: Tailwind CSS Design System for DexTrader Next.js Frontend
category: frontend_style
scope:
    - '**'
source_files:
    - frontend/tailwind.config.ts
    - frontend/app/globals.css
    - frontend/postcss.config.mjs
    - frontend/package.json
    - frontend/app/layout.tsx
    - frontend/components/Navbar.tsx
    - frontend/components/MarketTable.tsx
---

## Approach

The frontend (`frontend/`) is a Next.js 14 application styled exclusively with **Tailwind CSS v3.4.4** (configured via `tailwind.config.ts` and processed through PostCSS + Autoprefixer). There is no separate component library, CSS-in-JS, or design-token package — visual identity lives in Tailwind's theme extension plus inline utility classes on React components.

## Key Files

- `frontend/tailwind.config.ts` — single source of truth for colors and content scanning.
- `frontend/app/globals.css` — root stylesheet that imports Tailwind layers and applies base body styles.
- `frontend/postcss.config.mjs` — enables `tailwindcss` and `autoprefixer` plugins.
- `frontend/package.json` — declares `tailwindcss`, `postcss`, `autoprefixer` as devDependencies; runtime deps are only `next`, `react`, `react-dom`, `ethers`.
- `frontend/app/layout.tsx` — root layout that imports `globals.css` and wraps every page in providers.
- `frontend/components/*.tsx` — all UI components compose Tailwind utilities directly in JSX `className` strings.

## Architecture and Conventions

### Color tokens
All colors go through Tailwind's theme extension in `tailwind.config.ts`. The app defines four semantic tokens under `theme.extend.colors`:

| Token | Value | Usage |
|---|---:|---|
| `background` | `#020817` | App background |
| `foreground` | `#f9fafb` | Default text color |
| `primary.DEFAULT` | `#22c55e` (green) | Accent / active nav links |
| `primary.foreground` | `#020617` | Text on primary surfaces |
| `secondary.DEFAULT` | `#0f172a` | Secondary surface |
| `secondary.foreground` | `#e5e7eb` | Text on secondary surfaces |

These are consumed via `bg-background`, `text-foreground`, `text-primary`, etc. No other custom color names exist in the config.

### Base styles
`app/globals.css` is minimal: it emits the three Tailwind layers (`base`, `components`, `utilities`) and applies `bg-background text-foreground antialiased` to `body` via `@apply`. This centralizes the dark-mode palette at the document level.

### Content scanning
`tailwind.config.ts` scans `./app/**/*.{js,ts,jsx,tsx,mdx}` and `./components/**/*.{js,ts,jsx,tsx,mdx}`. Styles outside these directories (e.g., `context/`, `lib/`, `hooks/`) are intentionally not scanned — they contain no markup.

### Layout structure
`layout.tsx` establishes a fixed chrome: a full-height flex column with a `DemoBanner`, `Navbar`, and a `<main>` element constrained by `container mx-auto px-4 py-6`. Every page inherits this shell.

### Responsive strategy
Responsive breakpoints follow Tailwind defaults. The Navbar hides its link list on small screens (`hidden md:flex`) and shows a mobile-only wallet button instead. Components use standard Tailwind responsive prefixes (`sm:`, `md:`, `lg:`) where needed.

### Component styling pattern
Components are "utility-first": they compose Tailwind classes directly in JSX rather than defining reusable CSS classes. Examples from `MarketTable.tsx`:
- Card containers: `rounded-xl border border-slate-800 bg-slate-950/60`
- Header bars: `p-4 border-b border-slate-800 flex items-center justify-between`
- Inputs: `bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:border-blue-500 transition-colors`
- Buttons: `bg-slate-800 hover:bg-slate-700 border border-slate-700 text-gray-400 hover:text-gray-200 rounded-lg px-3 py-2 text-sm transition-colors`
- Positive/negative indicators: conditional `text-emerald-400` vs `text-red-400` based on data values.

### Dark theme
The entire app is dark by default — there is no light-mode toggle and no `dark:` variant usage observed. Backgrounds consistently use `slate-950`/`slate-900`/`slate-800` tones; text uses `gray-200`/`gray-300`/`gray-400`/`gray-500` scale.

### Typography
No custom font family is configured. Monospace numbers use Tailwind's built-in `font-mono`; headings rely on the system sans-serif stack.

### State-driven visuals
Conditional class composition drives state-based appearance (e.g., active nav link uses `text-primary font-medium` when `pathname === link.href`; gainers/losers rows switch between emerald/red text).

## Conventions and Constraints

- **Single source of truth for colors**: All brand colors are defined in `tailwind.config.ts` under `theme.extend.colors` and referenced via Tailwind's `bg-*` / `text-*` utilities. Hard-coded hex literals appear only in `globals.css`'s `@apply` rules.
- **No custom CSS modules or SCSS**: The repo contains no `.scss`, `.module.css`, or CSS-in-JS style files beyond `globals.css`.
- **Utility-first components**: Components do not define their own CSS classes; styling is expressed inline via `className` strings composed of Tailwind utilities.
- **Content scanning scope**: Only files under `app/` and `components/` are scanned for Tailwind classes; anything else will not be included in the build output.
- **PostCSS pipeline**: `postcss.config.mjs` enforces that both `tailwindcss` and `autoprefixer` run on every stylesheet.
- **Dark-only theme**: The app has no light-mode support and does not use `prefers-color-scheme` or `dark:` variants — the palette is fixed to dark tones.
- **Container constraint**: Page content is wrapped in `container mx-auto px-4 py-6` in `layout.tsx`, giving every route a consistent max-width and padding.