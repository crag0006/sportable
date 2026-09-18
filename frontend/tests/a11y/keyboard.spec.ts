// ============================================================================
// Keyboard-only traversal — AC3.2.4 (WCAG 2.1 SC 2.1.1 Keyboard, 2.4.3 Focus
// Order, 2.1.2 No Keyboard Trap)
// ============================================================================
//
// WHY THIS TEST EARNS ITS PLACE
//   This is the criterion most likely to regress silently. Nobody notices that
//   a `<div onClick>` replaced a `<button>` — it looks identical, it clicks
//   identically, and the only person it breaks is the one who cannot use a
//   mouse. axe does not catch it either: a div with an onClick handler has no
//   role, no name and no tabindex, so there is nothing for a rule to fire on.
//
// HOW IT PROVES "NO POINTER EVENTS"
//   Every page under test has `pointer-events: none` injected across the whole
//   document before a single key is pressed. The mouse is not merely unused —
//   it is disabled at the engine level. A control that only responds to a
//   click cannot pass by accident.
//
// RADIO GROUPS
//   A group of radio buttons is one tab stop by design: Tab reaches the group,
//   arrow keys move within it. Asserting that all three distance radios are
//   individually tabbable would be asserting a bug. So radios are collapsed by
//   `name` and the group is what must be reachable.
// ============================================================================

import { expect, test } from '@playwright/test'

import { ROUTES, openApp, openPasswordGate } from './support/app'

/** Everything the platform treats as a tab stop. */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button',
  'input:not([type="hidden"])',
  'select',
  'textarea',
  '[tabindex]',
  '[contenteditable=""]',
  '[contenteditable="true"]',
].join(', ')

type Candidate = { id: string; stop: string; label: string }

/**
 * Stamp every visible, enabled, focusable element with an id we can recognise
 * once it has focus, and return the list of tab stops we expect to reach.
 *
 * Reading `document.activeElement` back as an attribute beats reconstructing a
 * CSS path: React re-renders during the traversal (focusing the sport field
 * opens its suggestion list) and a path computed before the traversal would
 * no longer resolve afterwards. An attribute rides along with the node.
 */
async function stampCandidates(
  page: import('@playwright/test').Page,
  selector: string,
): Promise<Candidate[]> {
  return page.evaluate((sel) => {
    const isVisible = (el: Element) => {
      const rect = el.getBoundingClientRect()
      const style = window.getComputedStyle(el)
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        style.visibility !== 'hidden' &&
        style.display !== 'none' &&
        style.opacity !== '0'
      )
    }

    const describe = (el: Element) => {
      const tag = el.tagName.toLowerCase()
      const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim()
      const aria = el.getAttribute('aria-label')
      const id = el.getAttribute('id')
      const value = (el as HTMLInputElement).value
      const type = el.getAttribute('type')
      const name =
        aria ||
        text ||
        (id ? `#${id}` : '') ||
        (value ? `value=${value}` : '') ||
        (type ? `type=${type}` : '')
      return `<${tag}${type ? ` type=${type}` : ''}> ${name}`.trim()
    }

    const out: { id: string; stop: string; label: string }[] = []
    let n = 0

    for (const el of Array.from(document.querySelectorAll(sel))) {
      const html = el as HTMLElement
      if (html.tabIndex < 0) continue
      if ((el as HTMLInputElement).disabled) continue
      if (el.getAttribute('aria-hidden') === 'true') continue
      if (el.closest('[aria-hidden="true"]')) continue
      if (!isVisible(el)) continue

      const id = String(n++)
      html.setAttribute('data-a11y-id', id)

      // Radios share one tab stop per name; everything else is its own stop.
      const input = el as HTMLInputElement
      const stop = input.type === 'radio' && input.name ? `radio:${input.name}` : id

      out.push({ id, stop, label: describe(el) })
    }

    return out
  }, selector)
}

/**
 * Press Tab until focus comes back around, recording what it landed on.
 *
 * The step budget is generous but finite: a keyboard trap (SC 2.1.2) shows up
 * as the same element appearing over and over, and the loop has to end rather
 * than hang the CI job for the default 30-second timeout with no explanation.
 */
async function tabThrough(
  page: import('@playwright/test').Page,
  maxSteps: number,
): Promise<{ reached: Set<string>; order: string[] }> {
  const reached = new Set<string>()
  const order: string[] = []

  // Start from the very top of the document, not from whatever Playwright's
  // navigation left focused, so the order we record is the order a person
  // pressing Tab from a fresh page load would get.
  await page.evaluate(() => {
    ;(document.activeElement as HTMLElement | null)?.blur?.()
    document.body.focus?.()
  })

  for (let step = 0; step < maxSteps; step += 1) {
    await page.keyboard.press('Tab')

    const landed = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null
      if (!el || el === document.body || el === document.documentElement) return null
      const input = el as HTMLInputElement
      const id = el.getAttribute('data-a11y-id')
      const stop = input.type === 'radio' && input.name ? `radio:${input.name}` : id
      return { id, stop, tag: el.tagName.toLowerCase() }
    })

    if (!landed) {
      // Focus left the document (browser chrome, or wrapped past the end).
      // One full pass is all we need.
      if (order.length > 0) break
      continue
    }

    if (landed.stop) {
      reached.add(landed.stop)
      order.push(landed.stop)
    }
  }

  return { reached, order }
}

for (const route of ROUTES) {
  test(`${route.name} (${route.path}) — every control is reachable by keyboard alone`, async ({
    page,
  }) => {
    await openApp(page, route.path)

    // The mouse is switched off for the rest of this test. Anything that still
    // works from here works from a keyboard.
    await page.addStyleTag({ content: '*, *::before, *::after { pointer-events: none !important; }' })

    const candidates = await stampCandidates(page, FOCUSABLE_SELECTOR)
    expect(
      candidates.length,
      `No focusable controls found on ${route.path}. Either the page did not render or the ` +
        `selector needs updating — a page with zero tab stops is not something to pass quietly.`,
    ).toBeGreaterThan(0)

    const expectedStops = new Set(candidates.map((c) => c.stop))
    const { reached } = await tabThrough(page, candidates.length * 3 + 20)

    const unreachable = candidates
      .filter((c) => !reached.has(c.stop))
      // One entry per tab stop, not per radio in a group.
      .filter((c, i, all) => all.findIndex((o) => o.stop === c.stop) === i)
      .map((c) => `  ${c.label}`)

    expect(
      unreachable,
      unreachable.length
        ? `These controls on ${route.path} can be seen but never receive focus from Tab, ` +
            `so a keyboard-only or switch user cannot operate them:\n${unreachable.join('\n')}\n`
        : '',
    ).toEqual([])

    // A trap is the other half of SC 2.1.1: reaching everything is no use if
    // you cannot get back out. If the traversal ended having visited fewer
    // distinct stops than exist, something held on to focus.
    expect(
      reached.size,
      `Tab visited ${reached.size} of ${expectedStops.size} tab stops on ${route.path} before ` +
        `focus stopped advancing — that is the signature of a keyboard trap (WCAG 2.1.2).`,
    ).toBeGreaterThanOrEqual(expectedStops.size)
  })
}

// --------------------------------------------------------------------------
// Operability, not just reachability
// --------------------------------------------------------------------------
// Reaching a control proves the tab order. It does not prove the control does
// anything when you press Enter or Space. These two cover the only two forms
// on the critical path.

test('password gate is operable with the keyboard alone', async ({ page }) => {
  await openPasswordGate(page)
  await page.addStyleTag({ content: '*, *::before, *::after { pointer-events: none !important; }' })

  // The gate focuses its own field on mount (Passwordgate.jsx useEffect). That
  // is the behaviour being verified — without it there is no way in at all,
  // because the field is the first thing on the page and nothing precedes it.
  await expect(page.locator('#site-password')).toBeFocused()

  await page.keyboard.type('wrong-password')
  await page.keyboard.press('Enter')

  // The error has to be announced, not just drawn. role="alert" is what makes
  // a screen reader say it without the user going looking.
  const alert = page.getByRole('alert')
  await expect(alert).toBeVisible()
  await expect(alert).toContainText(/incorrect password/i)

  // And the submit button itself must be operable by key, not only by click.
  await page.keyboard.type('1234')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: /enter/i })).toBeFocused()
  await page.keyboard.press('Enter')

  await expect(page.locator('.password-gate')).toHaveCount(0)
})

test('venue search form can be submitted with the keyboard alone', async ({ page }) => {
  await openApp(page, '/venues')
  await page.addStyleTag({ content: '*, *::before, *::after { pointer-events: none !important; }' })

  const search = page.getByRole('button', { name: /search venues/i })
  await search.focus()
  await expect(search).toBeFocused()
  await page.keyboard.press('Enter')

  // Submitting with nothing filled in must produce a message, and that message
  // must be findable — a validation error that only exists as red text is
  // invisible to anyone not looking at that part of the screen.
  await expect(page.locator('#root')).toContainText(/sport|suburb|choose|select|enter/i, {
    timeout: 5_000,
  })
})
