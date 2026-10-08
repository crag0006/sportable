// ============================================================================
// Heading structure — AC3.2.3 (logical heading order)
// WCAG 2.1 SC 1.3.1 Info and Relationships (A), SC 2.4.6 Headings and Labels
// ============================================================================
//
// WHY THIS IS NOT LEFT TO axe
//   axe does have a `heading-order` rule, but it carries the `best-practice`
//   tag and no WCAG tag, so it is filtered out of axe.spec.ts along with every
//   other opinion. AC3.2.3 names heading order as a requirement, not an
//   opinion, so it is asserted here directly.
//
// WHY HEADING ORDER MATTERS MORE THAN IT LOOKS
//   Screen-reader users navigate a page by jumping heading to heading — it is
//   the equivalent of scanning with your eyes. A skipped level (h1 straight to
//   h3) announces a section that does not exist, and a page with no h1
//   announces itself as untitled. Both are invisible to anyone reading the
//   page with their eyes, which is exactly why they need a machine to catch
//   them.
//
// WHAT IS ASSERTED
//   1. Exactly one h1 per page.
//   2. No skipped levels on the way down.
//   3. Landmarks: a <main> exists, so "skip to content" has somewhere to go.
// ============================================================================

import { expect, test } from '@playwright/test'

import { ROUTES, openApp } from './support/app'
import { announceKnown, partition } from './support/known-issues'

const CHECK = 'heading-order'

type Heading = { level: number; text: string }

for (const route of ROUTES) {
  test(`${route.name} (${route.path}) — headings form a logical outline`, async ({ page }) => {
    await openApp(page, route.path)

    const headings: Heading[] = await page.evaluate(() => {
      const visible = (el: Element) => {
        const rect = el.getBoundingClientRect()
        const style = window.getComputedStyle(el)
        return rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
      }

      return Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'))
        .filter(visible)
        .map((h) => ({
          level: Number(h.tagName.slice(1)),
          text: (h.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 60),
        }))
    })

    const problems: string[] = []

    const h1s = headings.filter((h) => h.level === 1)
    if (h1s.length === 0) {
      problems.push(
        `No <h1>. The page has no announced title; the first heading is ` +
          `<h${headings[0]?.level ?? '?'}> "${headings[0]?.text ?? '(no headings at all)'}".`,
      )
    } else if (h1s.length > 1) {
      problems.push(
        `${h1s.length} <h1> elements: ${h1s.map((h) => `"${h.text}"`).join(', ')}. ` +
          `A page has one title.`,
      )
    }

    let previous = 0
    for (const heading of headings) {
      if (previous !== 0 && heading.level > previous + 1) {
        problems.push(
          `Heading level jumps from h${previous} to h${heading.level} at "${heading.text}" — ` +
            `an h${previous + 1} is missing between them.`,
        )
      }
      previous = heading.level
    }

    // The whole page is treated as one finding: a heading outline is a single
    // structure, and listing each skipped level as its own snag-list entry
    // would mean editing the list for every copy change.
    const findings = problems.length
      ? [
          {
            target: 'document',
            detail:
              `Heading outline on ${route.path} is not logical:\n    ` +
              `${problems.join('\n    ')}\n    Outline as rendered: ` +
              `${headings.map((h) => `h${h.level}`).join(' → ') || '(none)'}`,
          },
        ]
      : []

    const result = partition(route.path, CHECK, findings)
    announceKnown(route.path, CHECK, result.known)

    expect(
      result.stale,
      result.stale.length
        ? `The accessibility snag list is out of date — these defects are fixed:\n  ${result.stale.join('\n  ')}\n`
        : '',
    ).toEqual([])

    expect(result.blocking, result.blocking.join('\n\n')).toEqual([])
  })

  test(`${route.name} (${route.path}) — has a main landmark`, async ({ page }) => {
    await openApp(page, route.path)

    // Not baselined: every route already satisfies this, so it is a pure
    // regression guard. A <main> is what "skip to content" skips to, and what
    // a screen reader's "jump to main" command targets.
    await expect(
      page.locator('main, [role="main"]'),
      `${route.path} has no <main> landmark, so there is nothing for a screen reader's ` +
        `"jump to main content" command to reach (WCAG 2.1 SC 1.3.1 / 2.4.1).`,
    ).toHaveCount(1)
  })
}
