// ============================================================================
// Playwright — accessibility gate (task I5)
// ============================================================================
//
// WHAT THIS IS FOR
//   Epic 3's Definition of Done says the relevant WCAG 2.1 guidelines are
//   "identified and tested". Identified is a document; tested is this file and
//   the specs under tests/a11y/. A guideline nobody can regress against is a
//   guideline the team will regress against.
//
// WHY IT RUNS AGAINST THE BUILT BUNDLE, NOT THE DEV SERVER
//   `vite dev` injects the React refresh runtime, keeps sourcemaps inline and
//   serves unminified CSS. None of that ships. The thing users get is
//   `dist/`, so that is the thing the gate tests — the same artefact
//   deploy-staging.yml syncs to S3.
//
// WHY THERE IS NO BACKEND HERE
//   CI has no AWS credentials, no database and no network access to third
//   parties (see ci.yml's header for why CI is deliberately powerless). Every
//   request the app makes to /api/* is intercepted in tests/a11y/support/app.ts
//   and answered from a fixture. A test that goes red because there is no
//   backend teaches the team to ignore the gate, which is worse than having no
//   gate at all.
//
// WHY CHROMIUM ONLY
//   axe-core's findings are engine-independent for the rules we fail on
//   (labels, names, roles, contrast, heading structure) — running the same
//   scan three times in three engines costs three times the minutes and finds
//   the same violations. Keyboard order is where engines genuinely differ, and
//   that is worth revisiting when the team has the budget for it.
// ============================================================================

import { defineConfig, devices } from '@playwright/test'

// One port, declared once: the webServer below binds it and BASE_URL points at
// it. Overridable so a developer who already has 4173 busy is not stuck.
const PORT = Number(process.env.A11Y_PORT ?? 4173)
const BASE_URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './tests/a11y',

  // An accessibility violation is deterministic: the same DOM produces the
  // same finding every time. Retrying would only hide a genuinely flaky test,
  // so failures here are real the first time.
  retries: 0,

  // Fail the run if someone commits `test.only` — otherwise the gate silently
  // shrinks to one test and nobody notices.
  forbidOnly: !!process.env.CI,

  // Workers are cheap (one static server, no shared state) but CI runners are
  // small; two keeps the wall clock down without thrashing.
  workers: process.env.CI ? 2 : undefined,

  // 'list' prints every assertion as it runs, which is what you want in a CI
  // log. The HTML report is written but never auto-opened — an auto-opening
  // browser hangs a CI job forever.
  reporter: process.env.CI
    ? [['list'], ['html', { open: 'never' }]]
    : [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    // Traces only on failure: enough to see what axe saw, without writing a
    // 50 MB artefact on every green run.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // A fixed starting viewport so the reflow spec's resizes are measured from
    // a known baseline rather than from whatever the runner defaults to.
    viewport: { width: 1280, height: 900 },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Build, then serve `dist/` statically. `vite preview` applies the SPA
  // history fallback, so a deep link like /venues/1 resolves to index.html the
  // same way CloudFront's custom error response does in staging.
  //
  // Locally the server is reused if one is already listening, so a re-run is
  // instant. In CI there is never an existing server, and reusing one would be
  // a correctness hazard: it could be serving a stale build.
  webServer: {
    // --host 127.0.0.1 is load-bearing. Left to itself `vite preview` binds
    // only the IPv6 loopback, and Playwright's readiness probe for
    // http://127.0.0.1:PORT then never connects — the run dies after two
    // minutes with a "timed out waiting for webServer" that tells you nothing
    // about the real cause.
    command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
})
