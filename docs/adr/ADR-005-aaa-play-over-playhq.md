# ADR-005 — AAA Play as the events source, not PlayHQ

| | |
|---|---|
| **Status** | Accepted |
| **Date decided** | 14 September 2026 — the date DS-09-D1 cleared the last blocker. The swap itself was settled between the source assessment of 11 September and the task document of 15 September; no single minute records it |
| **Date recorded** | 15 September 2026 |
| **Decider** | Team lead, on the recommendation of the data engineering lead (DS-09-D1) |
| **Affects** | The whole of Epic 4, AC4.1.1, AC4.2.1, and the search form the Frontend team builds |

---

## Context

Epic 4 needs a register of sporting events across Victoria. The plan was PlayHQ.

**PlayHQ cannot be planned around.** Its API needs a key; the key is approved by
**both** PlayHQ and the governing body of **each sport**; it is therefore issued
**per sport**, not per project; and **no approval timeline exists**. Requests
have been made and remain open. They may well be granted — after submission,
which is the same as not at all for a nine-week iteration.

That is not a technical objection to PlayHQ. It is a scheduling one, and it is
the kind that does not improve by waiting.

## Options considered

| Option | Access | Why it was or was not viable |
|---|---|---|
| **PlayHQ** | Key, approved by PlayHQ **and** each sport's governing body, issued per sport, no timeline | Requests stay open. Iteration 2 cannot be planned around an approval nobody can date |
| **AAA Play** | **None.** `/wp-json/` reports `"authentication": []` — no key, no signup, no header, no Parameter Store entry | Chosen |
| ~~The AAA Play dated `event` post type~~ | Not registered for REST — `/wp-json/wp/v2/event` returns 404 | Roughly ten items, HTML only, no structured venue or time. Ten items do not justify a scraper whose selectors break on the next theme update |

## Decision

**AAA Play, registered as DS-09.** A Victorian Government funded directory run
by Reclink Australia under the Access for All Abilities programme, exposed as an
open WordPress REST API.

### Verified against the live API, 15 September 2026

Pulled rather than taken on trust:

| Claim | Detail |
|---|---:|
| Activities | **532** — `X-WP-Total` on `/wp/v2/activity` |
| Facilities | **552** — `X-WP-Total` on `/wp/v2/facility` |
| Organisations | **178** — `X-WP-Total` on `/wp/v2/organisation` |
| Requests for a full pull | **18** |
| Facilities geocoded | 552 / 552 carry `facility_location.lat/lng` |
| Activities carrying a facility id | 516 / 532 |

**Eighteen, not fourteen.** Six activity pages at `per_page=100`, six facility,
two organisation, then `activity_type`, `age_range`, `lga` and `region` once
each. Both the source assessment and the task document say fourteen, which
counts the post-type pages and forgets the four taxonomies. It matters for the
fetch function's timeout sizing.

> **One figure is behind.** The DS-09 card records `coverage.records_total: 530`
> from the pull of 11 September. The register moved to 532 by 15 September. Read
> the real count out of the landed payload and update the card — and note that
> this is exactly the reason DS-09 needs a count-drift guard that a pinned file
> hash would have given for free.

## What it cost us

### AAA Play publishes no event dates, and we are not deriving any

This is the price of the decision and it is visible on screen, so it is recorded
here rather than discovered at the demo.

AAA Play activities are **ongoing programmes, not dated event instances**. The
only temporal fields in the payload are:

| Field | What it is | Coverage |
|---|---|---:|
| `acf.weekday` | An array, e.g. `["saturday"]` | **393 of 532** (73.9%) |
| `acf.activity_when` | A coarse band — morning / afternoon / evening | **292 of 532** (54.9%) |
| `date`, `modified` | WordPress **publish** timestamps — not event dates | — |

There is no start date, no end date, no season and no clock time anywhere in the
post type.

**The team decided to show the recurrence exactly as published and derive
nothing.** An event carries its weekday and its time band and nothing more. The
139 activities (26.1%) with no published weekday say so, rather than being
dropped or given an invented schedule. A date-range filter cannot apply to a
programme with no dates and must not be silently widened to look as though it
did.

**The consequence for the acceptance criteria:**

- **AC4.1.1's Start Date and End Date fields have no data behind them.** The
  date-range filter is out of scope for Iteration 2. The search runs on sport,
  suburb/postcode and accessibility — the fields AC4.1.1 makes mandatory.
- **AC4.2.1's "date and time" is partial.** Published weekday and time band
  only.

Either drop the two date inputs from the form or reword those criteria to
day-of-week. Both are honest, and it is a wording change rather than engineering
work. **What is not acceptable is leaving a date picker on screen that silently
matches nothing.**

### The source publishes no licence, and we proceeded anyway

Every other source in the register is CC BY from a government publisher. AAA
Play is not.

The site publishes **no licence instrument**. It carries a disclaimer and a
Reclink privacy statement, and the footer asserts copyright in the State
Government of Victoria. There is no CC BY, no ODbL and no terms-of-use page to
cite. So the card records what is true:

```yaml
licence:
  name: No licence stated
  restricts_caching: null
  restricts_redistribution: null
  restricts_derived_works: null
```

**The three `restricts_` flags are null rather than false, deliberately.** False
would assert that the publisher permits caching, redistribution and derived
works, which nobody has established. Null reads as *not established*, which is
true. This is the register applying to itself the rule it applies to every
facility: an absence of published information is recorded as an absence, never
inferred into a positive.

The team proceeded under decision **DS-09-D1** (14 September 2026), on the
reading that constraint C2's operative obligation is naming the publisher and
stating the purpose of display rather than requiring an open licence. The
controls on that decision are: attribution on every listing and in the Sources
and licences view, no bulk redistribution, no personal data stored, no status
derived from the source, and a notification to Reclink.

**The residual risk is recorded as unestablished, not granted.** In the absence
of a licence the default position under Australian copyright law is that rights
are reserved. The controls reduce the scope and consequence of the use; they do
not make it authorised. DS-09-D1 says so in those words rather than describing
the question as closed.

> **One document still disagrees with the build.** §2.2 of the Design and
> Architecture document reads *"Every dataset carries an open licence and
> displayed attribution."* DS-09 does not. A submitted design document
> contradicting the code is a worse outcome than either reading of C2 on its
> own. One sentence to fix, and it is owed before submission.

### Smaller things the swap changed

- **`tier: reference`, not `live_api`.** The fetch handler's
  `FETCHABLE_TIERS = {"reference", "transit", "static"}` does not contain
  `live_api`, so the card the task document specifies would have been **skipped
  silently on every scheduled run**.
- **The table is `program`, not `event`.** These recur weekly with no dates.
  Calling the table `event` invites someone to add a date column and fill it
  from description prose.
- **The eighteen responses land as one S3 object**, `aaaplay/dt=…/aaaplay.json`,
  not as a file per endpoint. The load handler is triggered per object and opens
  one transaction per object; separate files would race, and the activity event
  would arrive unable to resolve a facility id that lives in a file the
  transformer cannot see. One object also means one SHA-256, so the existing
  change detection works unchanged — verified, a second run returns `no_change`
  with reason `identical_payload_hash`.

## Revisit when

- **PlayHQ approvals arrive.** They are per sport, so a partial grant is the
  likely shape. A source that covers three sports with real dates alongside one
  that covers everything without them is a product decision before it is a data
  one — and AC4.1.1's date fields come back into play only for the sports that
  are covered.
- **Reclink responds, or objects.** DS-09-D1's review trigger is explicit:
  revisit if Reclink responds with terms, if the project continues commercially
  past submission, if any export or public re-serving is proposed, or if the
  facility points are persisted rather than re-geocoded.
- **The ACF field set changes.** It is not a contract. The runbook covers what
  to do.

## See also

- [ADR-006](ADR-006-provider-claims-are-not-confirmed.md) — what AAA Play's facility fields may and may not say
- [ADR-004](ADR-004-victorian-scope-over-greater-melbourne.md) — the scope change this source forced
- `data/sources/DS-09_aaaplay.yaml` — the card, the licence position and DS-09-D1
- `data/ingestion/extractors/aaaplay.py` — the collector, and why eighteen responses are one object
- `docs/runbooks/operations.md` — forcing a reload, and what to do when the field set moves
