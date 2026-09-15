// ============================================================================
// Shared setup for the accessibility gate
// ============================================================================
//
// Two problems stand between a headless browser and a renderable SportAble
// page, and both are solved here rather than in every spec:
//
//   1. The whole app sits behind PasswordGate (src/pages/Passwordgate.jsx),
//      which is a client-side gate keyed on sessionStorage. Without a bypass,
//      every scan would be a scan of the password form.
//
//   2. Every page calls /api/v1/* on mount. CI has no backend (ci.yml holds no
//      AWS credentials by design), so those calls are intercepted and answered
//      from fixtures below. The app does degrade gracefully when they fail —
//      Home.jsx falls back to a hard-coded sport list — but "gracefully
//      degraded" is not the state we want to certify as accessible, and an
//      unstubbed call makes the DOM depend on network timing, which is how you
//      get a flaky gate.
// ============================================================================

import type { Page, Route } from '@playwright/test'

/** Key and value used by src/pages/Passwordgate.jsx. */
const GATE_STORAGE_KEY = 'sportable_authenticated'

/**
 * Pages the gate scans.
 *
 * Deliberately the routes that a person actually lands on. The map-heavy
 * directions view (/venues/:id/directions) is left out on purpose: Leaflet
 * renders a canvas of third-party tiles that cannot load without network
 * access, so anything axe reported about it would be about the empty shell,
 * not about what a user sees. It gets its own test when the tiles are served
 * from our own origin.
 */
export const ROUTES = [
  { name: 'landing', path: '/' },
  { name: 'venue search', path: '/venues' },
  { name: 'venue detail', path: '/venues/1' },
] as const

/**
 * Fixture responses, shaped to match what src/api/venues.js unwraps.
 *
 * These are intentionally small. The gate is testing markup semantics, not
 * data; a fixture that grows to mirror the real API is a fixture that starts
 * drifting from it.
 */
const API_FIXTURES: Record<string, unknown> = {
  '/api/v1/config': {
    distance_bands_m: [250, 500, 1000],
    default_distance_m: 500,
    max_results: 20,
  },
  '/api/v1/sports': {
    sports: ['Badminton', 'Basketball', 'Netball', 'Swimming', 'Tennis'],
  },
  '/api/v1/suburbs': {
    suburbs: [
      { label: 'Melbourne CBD 3000' },
      { label: 'Carlton 3053' },
      { label: 'Preston 3072' },
    ],
  },
}

/**
 * Answer every /api/* request from a fixture, and never let one reach the
 * network.
 *
 * Anything without a fixture gets the API's real not-found envelope rather
 * than a hang or an abort: the frontend has error paths for a 404 and they
 * should be the paths under test, not a timeout. The content type matters —
 * deploy-staging.yml's smoke test guards the same property in staging, because
 * an API 404 that arrives as HTML is a bug the frontend cannot parse.
 */
export async function stubApi(page: Page): Promise<void> {
  await page.route('**/api/**', async (route: Route) => {
    const path = new URL(route.request().url()).pathname
    const fixture = API_FIXTURES[path]

    if (fixture !== undefined) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixture),
      })
      return
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'not_found', message: `No fixture for ${path}` },
      }),
    })
  })
}

/**
 * Mark the session as past the password gate.
 *
 * addInitScript, not an evaluate after navigation: PasswordGate reads
 * sessionStorage in its useState initialiser, so the value has to exist before
 * the bundle runs or the gate renders first and the route never mounts.
 */
export async function bypassPasswordGate(page: Page): Promise<void> {
  await page.addInitScript(
    ([key]) => {
      window.sessionStorage.setItem(key, 'true')
    },
    [GATE_STORAGE_KEY],
  )
}

/**
 * Open a route with the gate bypassed and the API stubbed, then wait until
 * React has actually painted something.
 *
 * `networkidle` is not used: with every request fulfilled from memory there is
 * no network to go idle, and Playwright's own docs discourage it. Waiting for
 * a real element inside #root is the honest signal that the app mounted.
 */
export async function openApp(page: Page, path: string): Promise<void> {
  await bypassPasswordGate(page)
  await stubApi(page)
  await page.goto(path)
  await page.waitForSelector('#root *', { state: 'attached' })
  // One frame after mount, so effect-driven content (sport list, venue cards)
  // is in the DOM before anything measures it.
  await page.waitForLoadState('domcontentloaded')
  await page.locator('#root').waitFor({ state: 'visible' })
}

/**
 * Open the password gate itself, with no bypass.
 *
 * This screen is the first thing every reviewer, marker and teammate sees, and
 * it is the only screen on the critical path that is a pure form. If it is not
 * operable by keyboard, nothing behind it can be reached at all.
 */
export async function openPasswordGate(page: Page): Promise<void> {
  await stubApi(page)
  await page.goto('/')
  await page.locator('.password-gate').waitFor({ state: 'visible' })
}
