// ============================================================================
// Known accessibility defects — the gate's snag list
// ============================================================================
//
// READ THIS BEFORE YOU ADD A LINE
//
// Every entry below is a real WCAG failure that exists in the UI today. They
// are listed here so that the gate fails on *new* defects from the day it
// lands, instead of being permanently red and therefore permanently ignored.
// This list is a debt register, not a set of exemptions: each line is a bug
// somebody has to fix, and fixing it means deleting the line.
//
// THREE PROPERTIES MAKE THIS SAFE
//
//   1. It is narrow. An entry matches one route, one check and one element.
//      The same rule failing on a different element still fails the build.
//
//   2. It cannot rot. If a listed defect no longer occurs, the test FAILS and
//      tells you to delete the line. A stale suppression is how a baseline
//      turns into a blindfold, so the gate refuses to carry one.
//
//   3. It can be switched off entirely. `A11Y_STRICT=1 npm run test:a11y`
//      ignores this file completely and shows the true state of the UI. That
//      is the command to run before you claim Epic 3's Definition of Done is
//      met — the DoD is about the product, not about the baseline.
//
// ADDING AN ENTRY REQUIRES A REASON THAT IS NOT "TO GO GREEN". If a change you
// are making introduces a violation, fix the violation.
// ============================================================================

export type KnownIssue = {
  /** Route path exactly as it appears in ROUTES, or 'password-gate'. */
  route: string
  /** Check id — see the constants each spec passes to `partition`. */
  check: string
  /** The element selector (axe target) or scope the finding was reported at. */
  target: string
  /** What is wrong, in one line, and what fixing it looks like. */
  note: string
}

/**
 * Set `A11Y_STRICT=1` to ignore this file and see every violation.
 */
export const STRICT = process.env.A11Y_STRICT === '1'

export const KNOWN_ISSUES: readonly KnownIssue[] = [
  // ---------------------------------------------------------------- contrast
  // WCAG 2.1 SC 1.4.3 Contrast (Minimum), AA. All three are the same mistake:
  // a muted grey (#61707b / var(--text-soft)) used for small body text on a
  // tinted background. It measures between 4.3 and 4.5:1 — just under the bar.
  // One token change fixes all three; darkening --text-soft to about #55636d
  // clears 4.5:1 against every background it is currently used on.
  {
    route: '/',
    check: 'axe:color-contrast',
    target: '.footer-bottom > p',
    note: 'Footer copyright line: 4.4:1 against the footer background, needs 4.5:1 (SC 1.4.3).',
  },
  {
    route: '/venues',
    check: 'axe:color-contrast',
    target: '.field:nth-child(1) > .field-hint',
    note: 'Sport field hint text: under 4.5:1. Same --text-soft token as the footer line.',
  },
  {
    route: '/venues',
    check: 'axe:color-contrast',
    target: '.field:nth-child(2) > .field-hint',
    note: 'Suburb field hint text: under 4.5:1. Same --text-soft token.',
  },
  {
    route: '/venues/1',
    check: 'axe:color-contrast',
    target: '.facility-beyond > .facility-body > .facility-top > div:nth-child(1) > p',
    note: '"Nearest published facility is N m away" on the pink beyond-limit card: 4.37:1 against #fde9e8.',
  },

  // ------------------------------------------------------------------ reflow
  // WCAG 2.1 SC 1.4.10 Reflow, AA. The venue detail page scrolls sideways at
  // 320 CSS px — the document measures 374px against a 320px viewport.
  //
  // Cause: two CSS grids whose single column is sized to min-content, so the
  // track grows to fit its widest child instead of the container.
  //   main.css:911  .venue-content  { display: grid; /* no column sizing */ }
  //   main.css:276  .facility-list  { display: grid; /* no column sizing */ }
  // Fix: give both `grid-template-columns: minmax(0, 1fr);`. Verified locally
  // that the two lines together take the document from 374px to 320px.
  {
    route: '/venues/1',
    check: 'reflow@320',
    target: 'document',
    note: 'Venue detail scrolls horizontally at 320px: .venue-content and .facility-list need grid-template-columns: minmax(0, 1fr).',
  },

  // ---------------------------------------------------------- heading order
  // WCAG 2.1 SC 1.3.1 Info and Relationships, A. A screen reader user
  // navigates by heading; a skipped level reads as a missing section and a
  // page with no h1 reads as a page with no title.
  {
    route: '/',
    check: 'heading-order',
    target: 'document',
    note: 'Landing jumps h1 → h3: the three Footer.jsx column headings ("Explore", "Data & sources", "About this project") should be h2.',
  },
  {
    route: '/venues/1',
    check: 'heading-order',
    target: 'document',
    note: 'Venue detail has no h1 — the venue name in VenueHero.jsx renders as h2, and the section cards below it as h3.',
  },
]

export type Finding = {
  /** Matched against KnownIssue.target. */
  target: string
  /** Full text shown when this finding blocks the build. */
  detail: string
}

export type Partitioned = {
  /** Findings that must fail the build. */
  blocking: string[]
  /** Findings matched by a baseline entry — reported, not failed. */
  known: string[]
  /** Baseline entries that matched nothing and should now be deleted. */
  stale: string[]
}

/**
 * Split a spec's findings into what blocks, what is already on the snag list,
 * and which snag-list lines have been fixed and should be removed.
 *
 * `route` and `check` together scope which baseline entries are eligible, so
 * a stale entry is detectable: any eligible entry no finding matched has been
 * fixed.
 */
export function partition(route: string, check: string, findings: Finding[]): Partitioned {
  if (STRICT) {
    return {
      blocking: findings.map((f) => f.detail),
      known: [],
      stale: [],
    }
  }

  const eligible = KNOWN_ISSUES.filter((k) => k.route === route && k.check === check)
  const matched = new Set<string>()

  const blocking: string[] = []
  const known: string[] = []

  for (const finding of findings) {
    const hit = eligible.find((k) => k.target === finding.target)
    if (hit) {
      matched.add(hit.target)
      known.push(`${finding.target} — ${hit.note}`)
    } else {
      blocking.push(finding.detail)
    }
  }

  const stale = eligible
    .filter((k) => !matched.has(k.target))
    .map(
      (k) =>
        `${k.route} / ${k.check} / ${k.target} — this defect no longer occurs. ` +
        `Delete the entry from tests/a11y/support/known-issues.ts.`,
    )

  return { blocking, known, stale }
}

/**
 * Print the snag-list hits as GitHub annotations so they are visible in the
 * Actions UI without anyone opening the log, and readable as plain text when
 * run locally.
 */
export function announceKnown(scope: string, check: string, known: string[]): void {
  for (const entry of known) {
    console.log(`::warning title=Known a11y defect (${check}) on ${scope}::${entry}`)
  }
}
