# ADR-006 — An AAA Play facility claim never produces a `confirmed` status

| | |
|---|---|
| **Status** | **Proposed** — the build already enforces it; task D5 still says the opposite. The team has to settle which one moves |
| **Date decided** | 15 September 2026 — enforced in the build and written up the same day |
| **Date recorded** | 15 September 2026 |
| **Decider** | Data engineering. **Not yet ratified by the team** |
| **Affects** | D5, D7, D8, D9, AC4.2.2, AC4.2.3, and what a user is told about a venue they may travel to |

---

## Context

The register has a rule, and it predates this iteration: **government records are
the only thing that can produce a `confirmed` facility status.** It is written
into the DS-05 card from Iteration 1 — *"no facility status traces to OSM;
government records remain the only thing that can produce a confirmed"* — and it
is what lets the product claim its statuses are derived from official data
rather than assembled from whatever anyone typed into a form.

Task **D5** of the Iteration 2 document maps an AAA Play `true` to `confirmed`.

**The build refuses to do this**, and the refusal is enforced in two places. This
ADR is the reasoning, because a refusal to follow the task document is exactly
the kind of thing that must not live in a commit message.

## The reasoning

### Government funding is not government publication

Reclink Australia is a **not-for-profit delivering a Victorian Government funded
programme**. That is a different thing from a government publisher. The card
records `government_published: false` on that basis, and the consequence is
structural rather than stylistic: nothing from this source may ever be written
into `venue`, `venue_amenity_status` or `venue_access_chain`.

**AAA Play describes programmes. It does not adjudicate facilities.**

### The evidence, and it is not subtle

`facility_changing_places` is `true` on **275 of 552** AAA Play facilities.

Changing Places is an accredited standard. Accreditation requires assessment
against the Changing Places Design Specification and a Statement of Compliance,
and an accredited facility **must appear on the National Public Toilet Map** —
which is DS-02, already in the register, where **the Victorian count is 163**.

> **A source cannot hold 275 of something the authoritative register counts 163
> of statewide.**

Providers are reading the field as *"has a change room"*. That is an entirely
reasonable thing for a programme coordinator filling in a web form to think it
means. It is not what the term means. Changing Places is also a **trade mark
held by the State of Victoria**, so publishing it against unaccredited venues is
not merely a data-quality error.

**If a `true` here became a `confirmed`, that one field alone would put roughly
112 false confirmations in front of users** — people deciding whether a trip is
possible on the strength of a facility that does not exist.

`facility_changing_places` is therefore not loaded at all. DS-02 remains the only
Changing Places evidence in the project.

### The booleans have no null state, so a `false` is not a `no` either

The same problem in the other direction. ACF checkboxes serialise as `true` or
`false`, and `false` means *nobody ticked the box*:

| Field | `false` on |
|---|---:|
| `facility_hearing_loops` | **548 of 552** |
| `facility_sensory_space` | **546 of 552** |
| `facility_wheelchair_accessible` | 230 of 552 (`true` on 322) |

Reading those as a recorded absence would put "no hearing loop" on 548 venues on
the strength of nobody having filled in a form. AC4.2.3 is explicit that
unavailable information reads **Unknown**, never "unavailable", so the transform
rule is fixed in the card rather than left to the loader: **`true` becomes a
published yes, `false` becomes `no_published_information`, never
`not_available`.** That half of D5 is built and tested.

The one field with genuine tri-state signal is `facility_accessible_car_spaces`:
`''` (169 records) is unknown, `0` (86 records) is a real published zero.

## Decision

**AAA Play's facility booleans are provider claims. They inform; they do not
adjudicate.**

1. Nothing from DS-09 writes to `venue`, `venue_amenity_status` or
   `venue_access_chain`.
2. The booleans are displayed — if they are displayed at all — **in their own
   block, under their own attribution, visibly separate from the four facility
   tiles.** Whether to display them is a product decision and is still open on
   the card; where they sit if displayed is not.
3. **An event's four facility statuses come from its matched DS-01 venue**, not
   from the AAA Play facility record.
4. Where there is no match, the honest answer is `no_published_information`.

`activity_access_needs` sits under the same rule for a different reason: it is
**cohort suitability, not a facility**. It says who a programme is designed for,
not what the venue has. It is populated on 251 of 530 activities and tagged
`wheelchair_accessible` on only 70, and the site's own PlayOn women's and girls'
**wheelchair basketball** programme carries an empty access-needs array. Empty is
no published information. It must never be the predicate that builds the events
list, and it must never populate AC4.2.2's four statuses.

Free text is under the same rule again. *"Free accessible parking is available on
site"* in a description is displayed as recorded provider text with attribution
and is never parsed into a status. **Prose is not a publication status.**

## Consequences

### D7 becomes a hard dependency of D8, not a parallel task

This is the scheduling consequence and it is the expensive one.

If AAA Play cannot supply facility status, the four tiles on an event come from
its matched DS-01 venue — so **without the venue matcher, every event reads
Unknown on all four.** D8 cannot start meaningfully until D7 lands.

The schema is ready: `program_venue.venue_id` exists, and a constraint requires
match evidence. **Nothing populates it yet.**

The matcher is also harder than the task document assumed. D7 specifies 75 m;
the build uses **150 m plus a trigram similarity of ≥ 0.3**, because testing
found false neighbours inside 20 m — a cafe five metres from a gym. **Distance
alone is not enough at any radius.**

### Nobody yet has the number that matters

Jiahe matched 552 facilities against 2,153 DS-01 venues and got **177 within
150 m**. That figure is stale twice over:

- **Wrong denominator.** Leisure centres host many programmes each. What matters
  is what share of the **514 linked activities** land on a matched facility, not
  what share of facilities match.
- **Stale baseline.** It was computed against the 31-council load. DS-01 is now
  statewide at 3,896 venues ([ADR-004](ADR-004-victorian-scope-over-greater-melbourne.md)),
  so the 220 facilities reported with nothing within two kilometres were largely
  regional venues that had simply not been loaded.

**Re-run it before designing anything on top of it.**

### Two of the four tiles have no AAA Play source at all

AC4.2.2 names accessible toilet, parking, transport and change facility:

| Required by AC4.2.2 | AAA Play field | Where it comes from |
|---|---|---|
| Accessible parking | `facility_accessible_car_spaces` | AAA Play — as a provider claim |
| Accessible change facility | `facility_accessible_changerooms` | AAA Play — as a provider claim. `facility_changing_places` is **not loaded** |
| Accessible toilet | none | DS-02 proximity join, else Unknown |
| Accessible transport | none | DS-03 PTV GTFS — **still has no transformer** |

Transport reads *"no published information"* for every event until DS-03 gets a
transformer. Under AC4.2.3 that is a **correct** answer, not a failure — but it
needs to be a decision on the record, taken on the day it is taken, rather than a
gap found at the demo. It is still open.

### What this costs, stated plainly

The product will show more Unknowns than it would have if a `true` were allowed
to mean `confirmed`. That is the trade. A screen full of Unknowns looks worse in
a demo and is worth more to the person reading it, because the alternative is
roughly 112 confidently wrong answers about whether a venue has a Changing
Places facility.

## Revisit when

- **The team settles it.** The task document and the build currently disagree,
  and D5, D7, D8 and D9 all depend on the answer. Building them on the wrong
  answer costs more than the discussion does. Either D5's mapping table changes
  or this ADR is superseded.
- **Reclink publishes provenance for a field**, or a field becomes sourced from a
  government record. The rule is about who published the claim, not about which
  source it arrived through.
- **A government publisher covers the same attributes.** DS-02 already does for
  Changing Places, which is why that field is excluded rather than demoted.

## See also

- [ADR-005](ADR-005-aaa-play-over-playhq.md) — why this source is in the register at all
- [ADR-004](ADR-004-victorian-scope-over-greater-melbourne.md) — why a regional venue often has nothing to say on parking
- `data/sources/DS-09_aaaplay.yaml` — `known_limitations`, and the open question on whether the booleans are displayed
- `data/sources/DS-05_openrouteservice.yaml` — where the government-records-only rule is written down
