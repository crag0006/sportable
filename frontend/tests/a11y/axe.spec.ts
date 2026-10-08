// ============================================================================
// axe-core scan — AC3.2.3 (meaningful labels on every control)
// ============================================================================
//
// WHAT FAILS THE BUILD
//   Any violation axe grades `serious` or `critical` that is not on the snag
//   list in support/known-issues.ts. Those are the ones that stop someone
//   using the page: a control with no accessible name, an image with no
//   alternative, text that cannot be read against its background, a form field
//   whose label is decorative only.
//
// WHAT DOES NOT FAIL THE BUILD
//   `moderate` and `minor` findings are printed as GitHub warnings instead.
//   That is a deliberate staging decision: raising the bar to `moderate` on
//   day one would have made this job red on arrival, and a job that is red on
//   arrival is a job people learn to route around. The findings are in the
//   log; when the count reaches zero, move the threshold and delete this
//   paragraph.
//
//   Heading order is the one thing deliberately NOT left to axe — its
//   `heading-order` rule is tagged best-practice rather than WCAG, so the tag
//   filter below excludes it. AC3.2.3 names heading order explicitly, so it
//   gets its own spec: structure.spec.ts.
//
// WHICH RULES
//   The WCAG 2.0 A/AA and WCAG 2.1 A/AA tag sets. Best-practice rules that
//   carry no WCAG success criterion are excluded — the Definition of Done is
//   written against WCAG 2.1, so that is what the gate enforces. Adding
//   'best-practice' would make the gate an opinion rather than a standard.
// ============================================================================

import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { ROUTES, openApp, openPasswordGate } from './support/app'
import { KNOWN_ISSUES, announceKnown, partition } from './support/known-issues'
import type { Finding } from './support/known-issues'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

// Severities that fail the build. See the header for why `moderate` is not
// here yet.
const BLOCKING = new Set(['serious', 'critical'])

type Violation = {
  id: string
  impact?: string | null
  help: string
  helpUrl: string
  nodes: { target: unknown[]; failureSummary?: string }[]
}

/**
 * Flatten axe's rule-then-node shape into one finding per element, because
 * that is the granularity the snag list works at: the same rule failing on a
 * new element must still fail the build.
 */
function toFindings(violations: Violation[]): { check: string; finding: Finding }[] {
  const out: { check: string; finding: Finding }[] = []

  for (const v of violations) {
    for (const node of v.nodes) {
      const target = node.target.map((t) => String(t)).join(' ')
      out.push({
        check: `axe:${v.id}`,
        finding: {
          target,
          detail:
            `[${v.impact}] ${v.id}: ${v.help}\n` +
            `    element: ${target}\n` +
            `    ${node.failureSummary?.replace(/\n/g, '\n    ') ?? ''}\n` +
            `    ${v.helpUrl}`,
        },
      })
    }
  }

  return out
}

/**
 * Run the scan, apply the snag list, and assert.
 *
 * Shared by the gate screen and the three app routes so that the reporting is
 * identical everywhere — the failure message is the whole value of this test,
 * and a message that differs per page is one people have to re-learn.
 */
async function assertNoBlockingViolations(
  page: import('@playwright/test').Page,
  scope: string,
): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  const violations = results.violations as unknown as Violation[]

  const advisory = violations.filter((v) => !BLOCKING.has(v.impact ?? ''))
  for (const v of advisory) {
    console.log(
      `::warning title=a11y advisory on ${scope}::[${v.impact}] ${v.id}: ${v.help} ` +
        `(${v.nodes.length} element(s))`,
    )
  }

  const serious = toFindings(violations.filter((v) => BLOCKING.has(v.impact ?? '')))

  // Group by rule so each rule gets its own snag-list scope; without this a
  // known contrast defect would also excuse an unrelated rule that happened to
  // fire on the same selector.
  const byCheck = new Map<string, Finding[]>()
  for (const { check, finding } of serious) {
    byCheck.set(check, [...(byCheck.get(check) ?? []), finding])
  }

  const blocking: string[] = []
  const stale: string[] = []

  for (const [check, findings] of byCheck) {
    const result = partition(scope, check, findings)
    announceKnown(scope, check, result.known)
    blocking.push(...result.blocking)
    stale.push(...result.stale)
  }

  // Snag-list entries whose rule fired nowhere at all this run are also stale.
  // Checking only the rules that fired would let a fixed defect linger.
  for (const check of new Set(
    KNOWN_ISSUES.filter((k) => k.route === scope && k.check.startsWith('axe:')).map(
      (k) => k.check,
    ),
  )) {
    if (!byCheck.has(check)) {
      stale.push(...partition(scope, check, []).stale)
    }
  }

  expect(
    stale,
    stale.length
      ? `The accessibility snag list is out of date — these defects are fixed:\n  ${stale.join('\n  ')}\n`
      : '',
  ).toEqual([])

  expect(
    blocking,
    blocking.length
      ? `axe found ${blocking.length} unlisted serious/critical violation(s) on ${scope}:\n\n  ` +
          `${blocking.join('\n\n  ')}\n`
      : '',
  ).toEqual([])
}

// The password gate is scanned separately because it is not behind itself.
test('password gate has no serious or critical accessibility violations', async ({ page }) => {
  await openPasswordGate(page)
  await assertNoBlockingViolations(page, 'password-gate')
})

for (const route of ROUTES) {
  test(`${route.name} (${route.path}) has no serious or critical accessibility violations`, async ({
    page,
  }) => {
    await openApp(page, route.path)
    await assertNoBlockingViolations(page, route.path)
  })
}

// --------------------------------------------------------------------------
// AC3.2.3, the explicit half: every interactive control carries a meaningful
// accessible name.
// --------------------------------------------------------------------------
//
// axe covers most of this through button-name / link-name / label, but it
// judges by presence, not by meaning. A link named "click here" passes axe and
// tells a screen-reader user nothing. This test rejects the handful of names
// that are demonstrably useless, which is as far as a machine can honestly go.
const USELESS_NAMES = [
  '',
  'click here',
  'here',
  'read more',
  'more',
  'link',
  'button',
  'submit',
  'image',
  'untitled',
  '...',
  '>',
  '→',
]

for (const route of ROUTES) {
  test(`${route.name} (${route.path}) — every control has a meaningful accessible name`, async ({
    page,
  }) => {
    await openApp(page, route.path)

    const offenders = await page.evaluate((useless: string[]) => {
      const bad = new Set(useless)
      const selector =
        'a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="link"]'

      const visible = (el: Element) => {
        const rect = el.getBoundingClientRect()
        const style = window.getComputedStyle(el)
        return (
          rect.width > 0 &&
          rect.height > 0 &&
          style.visibility !== 'hidden' &&
          style.display !== 'none'
        )
      }

      // A pragmatic accessible-name computation: enough to catch a control
      // with nothing at all, without shipping a second accessibility engine.
      const nameOf = (el: Element): string => {
        const labelled = el.getAttribute('aria-labelledby')
        if (labelled) {
          const text = labelled
            .split(/\s+/)
            .map((id) => document.getElementById(id)?.textContent ?? '')
            .join(' ')
            .trim()
          if (text) return text
        }

        const aria = el.getAttribute('aria-label')?.trim()
        if (aria) return aria

        if (
          el instanceof HTMLInputElement ||
          el instanceof HTMLSelectElement ||
          el instanceof HTMLTextAreaElement
        ) {
          const labels = Array.from(el.labels ?? [])
          const text = labels
            .map((l) => l.textContent ?? '')
            .join(' ')
            .trim()
          if (text) return text

          const placeholder = el.getAttribute('placeholder')?.trim()
          if (placeholder) return placeholder

          const title = el.getAttribute('title')?.trim()
          if (title) return title

          if (el instanceof HTMLInputElement && (el.type === 'submit' || el.type === 'button')) {
            return el.value
          }
          return ''
        }

        const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim()
        if (text) return text

        const alt = el.querySelector('img[alt]')?.getAttribute('alt')?.trim()
        if (alt) return alt

        return el.getAttribute('title')?.trim() ?? ''
      }

      return Array.from(document.querySelectorAll(selector))
        .filter(visible)
        .map((el) => ({ name: nameOf(el), html: el.outerHTML.slice(0, 160) }))
        .filter((entry) => bad.has(entry.name.toLowerCase()))
        .map((entry) => `"${entry.name}" → ${entry.html}`)
    }, USELESS_NAMES)

    expect(
      offenders,
      offenders.length
        ? `Controls with a missing or uninformative accessible name on ${route.path} ` +
            `(WCAG 2.1 SC 4.1.2 / 2.4.4):\n  ${offenders.join('\n  ')}\n`
        : '',
    ).toEqual([])
  })
}
