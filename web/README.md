# grip marketing site

Next.js (App Router) marketing site for the [grip](../README.md) Python SDK — a
CDP-native browser interface for AI agents. Deployed at
https://grip-browser.vercel.app.

## The one hard rule

Every number on this page comes from `lib/metrics.ts`, not from a component. If
you need a stat, import it from there; if it isn't there, it doesn't ship. A
median never ships without its range attached — `lib/metrics.ts` enforces this
by shape (see its header comment for the two rules and why the page once broke
them). If you're re-running the benchmark, swap the values in that one file and
the whole page moves with it.

`/changelog` renders the repo root `CHANGELOG.md` at build time — it is not a
second source of truth, just a render of the same file `grip` ships with.

## Commands

```bash
npm run dev     # local dev server
npm run build   # production build (also used to verify icon/manifest routes)
npm run lint
```

## Deploy

Vercel, project root `web/`. Push to the tracked branch triggers a deploy;
`npm run build` locally is the pre-push sanity check, not a substitute for
checking the live URL after deploy.

## Structure

- `app/` — routes. `page.tsx` is the landing page, `layout.tsx` holds fonts/theme/metadata, `icon.tsx`/`apple-icon.tsx`/`manifest.ts` are the generated favicon and PWA manifest, `robots.ts`/`sitemap.ts` are the generated SEO files.
- `lib/metrics.ts` — the numbers, see above.
- `components/` — one file per landing-page section (`hero.tsx`, `hero-visual.tsx`, `mechanisms.tsx`, `delta.tsx`, `task-success.tsx`, `token-chart.tsx`, `token-cost.tsx`, `limits.tsx`, `mcp.tsx`, `install.tsx`, `hardening.tsx`, `features.tsx`, `footer.tsx`, `nav.tsx`) plus shared pieces (`cli.tsx`, `code-showcase.tsx`, `copy-button.tsx`, `theme-provider.tsx`, `theme-toggle.tsx`, `reveal.tsx`, `section.tsx`, `icons.tsx`).
- `components/dither-kit/` — local chart primitives (axes, scales, area/dot series, tooltip, legend) built on `d3-scale`/`d3-shape`; the token and mechanism charts on the landing page are composed from these rather than a chart library.
- `components/ui/` — shadcn primitives.
