# Frontend AGENTS.md

React 19 + TypeScript SPA built with Vite. Read the root `AGENTS.md` first.

## Layout

| Path | What |
|---|---|
| `components/ui/` | Small primitives (button, card, input, badge, ...). Styled for the dark palette. |
| `components/layout/` | App shell: `Layout`, `Sidebar`, banners. |
| `components/safety/` | Tier badges, action display, enforce preflight, undo controls. |
| `lib/utils.ts` | `cn()` — clsx + tailwind-merge. |
| `services/api.ts` | **The** API client. Typed, centralized error handling. |
| `stores/` | Zustand stores (branding, settings, runs). |
| `pages/` | Route components. |
| `theme.ts` | Semantic tokens mirroring the CSS variables in `index.css`. |

## Conventions

- **Use `services/api.ts`, never raw `fetch` in a component.** Every endpoint
  gets a typed function there. This is where error shape, headers, and base URL
  live.
- **Use the theme tokens**, not literal hex values. The app is dark-first; the
  semantic names (`surface`, `border`, `muted`, `danger`) exist so a palette
  change is one file.
- Build output goes to `backend/static/` and is served by FastAPI in
  production. In dev, Vite proxies `/api` to `:8000`.

## Surfacing the safety model

The UI is the last place a destructive action can be caught, so it carries real
weight. When touching anything that displays or triggers an action:

- Show the **tier badge** and, when the backend downgraded the action, show
  `requested_action` struck through beside `effective_action` with the
  `downgrade_reason` available on hover. A silent downgrade is a lie to the
  reviewer — they will assume the policy ran as written.
- **Tier 3 is never a one-click action.** The enforce flow is a preflight panel
  listing affected resources grouped by tier, plus type-to-confirm on the
  workspace name, scoped to a single run.
- Tier 2 rows get an **undo** button; Tier 3 rows get an explicit irreversible
  marker.
- The enforcement-enabled banner is deliberately hard to ignore. Don't soften it.
