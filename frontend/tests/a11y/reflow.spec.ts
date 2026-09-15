// ============================================================================
// Reflow — AC3.2.1 (WCAG 2.1 SC 1.4.10 Reflow, AA)
// ============================================================================
//
// WHAT THE CRITERION ACTUALLY SAYS
//   Content must be presentable without loss of information or functionality,
//   and without requiring scrolling in two dimensions, at a viewport 320 CSS
//   pixels wide. 320px is not a phone size picked at random: it is 1280px
//   zoomed to 400%, which is how the criterion is written. Someone who needs
//   large text is browsing a 320px-wide viewport whether or not they own a
//   phone.
//
// WHY THREE WIDTHS AND NOT ONE
//   320px is the pass/fail line. 853px (1280 at 150%) and 640px (1280 at 200%)
//   are the widths a partially-sighted user browsing our staging URL on a
//   laptop will actually be at, and they are where a fixed-width table or a
//   `min-width: 900px` container shows up first. Testing only 320 lets a
//   layout break at 640 and still pass, because many designs switch to a
//   mobile stylesheet below some breakpoint and skip the middle entirely.
//
// HOW "NO CLIPPED CONTENT" IS MEASURED
//   Two checks, because they fail differently:
//     1. The document must not scroll horizontally — scrollWidth must not
//        exceed clientWidth. This is the criterion verbatim.
//     2. No individual visible element may extend past the right edge of the
//        viewport. An element pushed beyond the edge inside an `overflow:
//        hidden` ancestor is invisible AND does not widen the document, so
//        check 1 alone reports a clean pass on a page whose text has been cut
//        in half. That is the failure mode worth catching.
// ============================================================================

import { expect, test } from '@playwright/test'

import { ROUTES, openApp } from './support/app'
import { announceKnown, partition } from './support/known-issues'

// The check id carries the width. Scoping snag-list entries per width matters:
// without it, the entry for /venues/1 at 320px would look "stale" to the very
// same route's passing test at 640px and fail the run for the wrong reason.
const checkFor = (width: number) => `reflow@${width}`

/**
 * The widths under test. `height` is generous so that vertical scrolling — the
 * one dimension the criterion permits — does not itself introduce a scrollbar
 * that skews the horizontal measurement.
 */
const WIDTHS = [
  { label: '320px — SC 1.4.10 reflow width (1280 at 400% zoom)', width: 320, height: 1200 },
  { label: '640px — 1280 at 200% zoom', width: 640, height: 1200 },
  { label: '853px — 1280 at 150% zoom', width: 853, height: 1200 },
] as const

/**
 * Sub-pixel slack.
 *
 * Browsers compute layout in fractional pixels and round scrollWidth up, so a
 * layout that fits exactly can report one pixel of overflow. One pixel is not
 * a reflow failure and treating it as one produces a gate nobody trusts.
 * Anything genuinely broken overflows by tens or hundreds of pixels.
 */
const TOLERANCE_PX = 2

for (const route of ROUTES) {
  for (const size of WIDTHS) {
    test(`${route.name} (${route.path}) reflows at ${size.width}px — ${size.label}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: size.width, height: size.height })
      await openApp(page, route.path)

      // Let the layout settle: web fonts, the hero image and any effect-driven
      // content all change widths after first paint.
      await page.waitForLoadState('load')
      await page.evaluate(
        () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      )

      const report = await page.evaluate((tolerance: number) => {
        const doc = document.documentElement

        const overflowing: string[] = []
        const viewportRight = doc.clientWidth

        for (const el of Array.from(document.body.querySelectorAll('*'))) {
          const style = window.getComputedStyle(el)
          if (
            style.display === 'none' ||
            style.visibility === 'hidden' ||
            style.opacity === '0'
          ) {
            continue
          }

          // Elements deliberately placed off-screen for screen readers only
          // ("skip to content" links, visually-hidden labels) are not clipped
          // content — they are correctly hidden content.
          const rect = el.getBoundingClientRect()
          if (rect.width === 0 || rect.height === 0) continue
          if (rect.right <= 0) continue

          // An element inside a container that scrolls horizontally on purpose
          // (a wide data table in its own scroller) satisfies the criterion:
          // the page does not scroll in two dimensions, that one region does.
          let inScroller = false
          let parent: Element | null = el.parentElement
          while (parent && parent !== document.body) {
            const ps = window.getComputedStyle(parent)
            if (ps.overflowX === 'auto' || ps.overflowX === 'scroll') {
              inScroller = true
              break
            }
            parent = parent.parentElement
          }
          if (inScroller) continue

          if (rect.right > viewportRight + tolerance) {
            const id = el.id ? `#${el.id}` : ''
            const cls =
              typeof el.className === 'string' && el.className
                ? `.${el.className.trim().split(/\s+/).slice(0, 3).join('.')}`
                : ''
            overflowing.push(
              `${el.tagName.toLowerCase()}${id}${cls} — right edge at ` +
                `${Math.round(rect.right)}px, viewport is ${viewportRight}px`,
            )
          }
        }

        return {
          scrollWidth: doc.scrollWidth,
          clientWidth: doc.clientWidth,
          // Deduplicate: one over-wide container reports itself and every
          // descendant, which buries the actual culprit under fifty lines.
          overflowing: Array.from(new Set(overflowing)).slice(0, 15),
          overflowCount: new Set(overflowing).size,
        }
      }, TOLERANCE_PX)

      const problems: string[] = []

      // --- check 1: the page itself must not scroll sideways ---
      if (report.scrollWidth > report.clientWidth + TOLERANCE_PX) {
        problems.push(
          `the document is ${report.scrollWidth}px wide against a ${report.clientWidth}px ` +
            `viewport, so the page scrolls horizontally`,
        )
      }

      // --- check 2: nothing is pushed out of sight ---
      if (report.overflowCount > 0) {
        problems.push(
          `${report.overflowCount} element(s) extend past the right edge and are clipped:\n    ` +
            report.overflowing.join('\n    '),
        )
      }

      // The route/width pair is one finding. Listing every overflowing element
      // separately would mean a snag-list entry per <div>, and the entries
      // would churn on every copy change — the defect is the layout, not the
      // fifty descendants it drags past the edge.
      const findings = problems.length
        ? [
            {
              // The width already lives in the check id, so the target names
              // the scope: the whole document at this width.
              target: 'document',
              detail:
                `At ${size.width}px (${size.label}), ${route.path} fails WCAG 2.1 SC 1.4.10 ` +
                `Reflow:\n  ${problems.join('\n  ')}\n`,
            },
          ]
        : []

      const check = checkFor(size.width)
      const result = partition(route.path, check, findings)
      announceKnown(`${route.path} @ ${size.width}px`, check, result.known)

      expect(
        result.stale,
        result.stale.length
          ? `The accessibility snag list is out of date — these defects are fixed:\n  ` +
              `${result.stale.join('\n  ')}\n`
          : '',
      ).toEqual([])

      expect(result.blocking, result.blocking.join('\n\n')).toEqual([])
    })
  }
}
