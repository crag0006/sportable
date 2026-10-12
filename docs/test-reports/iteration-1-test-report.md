# Iteration 1 — Test Report

**SportAble Melbourne** · FIT5120 Studio Project · Team Lumera

| | |
|---|---|
| **URL tested** | https://sportablemelbourne-iteration1.me/ |
| **Build** | `dev` |
| **Date** | 3 September 2026 |
| **Scope** | Epic 1 — US1.1, US1.2, US1.3 · all 14 acceptance criteria |
| **Method** | Automated browser testing (Playwright / Chromium), desktop 1200×761 and mobile 390×844, plus direct API calls |
| **Tester** | Infrastructure / Platform |

---

## Result

**7 pass · 5 partial · 2 fail**

The system works end to end. Real venues, real distances measured in PostGIS, served from a custom domain over HTTPS, with the API and database behind it. **Every failure below is the frontend not rendering data the API already returns.** Nothing is broken in the backend, the data, or the infrastructure.

The two acceptance criteria that carry the product's ethics — grouping undocumented venues rather than dropping them, and never showing an unknown as a no — both pass. Those were the hardest to get right.

---

## Summary by user story

### US1.1 — Search for venues from the landing page

| AC | Result | Finding |
|---|:---:|---|
| **1.1.1** Form visible without scrolling; sport field offers only sports in the data | ✅ Pass | Search button bottom at 629px in a 761px viewport. Sport list comes from `/api/v1/sports` — 29 sports, all drawn from `venue_sport` |
| **1.1.2** Results show name, suburb, sport, distance; sorted by distance | ⚠️ Partial | Name, suburb and sports shown; ordering is correct. **The distance itself is never rendered** — see F-1 |
| **1.1.3** The point distances are measured from is named on screen | ❌ Fail | See F-2 |
| **1.1.4** Unrecognised location names the covered area or offers near matches | ⚠️ Partial | An error is shown rather than a bare empty list, which is the important half. The message does neither of the two things the AC asks for — see F-3 |
| **1.1.5** Results within 3 seconds | ✅ Pass | Three consecutive runs: **1052 ms, 448 ms, 846 ms** |

### US1.2 — Filter results by the access facilities I need

| AC | Result | Finding |
|---|:---:|---|
| **1.2.1** Four filters available; each names its dataset | ⚠️ Partial | All four present and correctly named. **No filter names its source dataset** |
| **1.2.2** Count updates immediately on every change, no reload, announced to assistive technology | ⚠️ Partial | `aria-live="polite"` is present ✅ and there is no page reload ✅. But the count does **not** change until Search is pressed — see F-4 |
| **1.2.3** Venues with no published information appear in a separate labelled group with its own count | ✅ **Pass** | Renders as `Missing accessibility information (10)`, collapsible, with a helpful *"Try removing an amenity or choosing a bigger distance."* |
| **1.2.4** 250 m / 500 m / 1 km re-evaluate without a new search; chosen limit shown beside every distance | ⚠️ Partial | The three bands work and are real radio inputs with accessible names. Re-evaluation requires a new search, and the limit is not repeated beside each distance |
| **1.2.5** Active filters visible and clearable individually or all at once | ✅ Pass | The ticked checkboxes are the visible state and are individually clearable; **Clear** clears all |

### US1.3 — Read the access status without opening every venue

| AC | Result | Finding |
|---|:---:|---|
| **1.3.1** Each result shows all four facility statuses | ✅ Pass | Toilet, parking, transport and change facility on every card |
| **1.3.2** Confirmed facilities show the measured distance **and the source that recorded it** | ❌ Fail | Distance shown (`216 m away`); no source named — see F-5 |
| **1.3.3** Unknown reads "No published information — check with the venue", never a yes or a no | ✅ **Pass** | Rendered verbatim. Verified against transport, which no source documents |
| **1.3.4** Status conveyed by icon **and** text, legible in greyscale, not colour alone | ✅ Pass | Icon + label + `✓`/`?` symbol with `aria-label`. Decorative icons carry `aria-hidden="true"` |

---

## Findings

### F-1 · Venue distance is never displayed — **HIGH**

The API returns it:

```json
{ "name": "Princes Park", "distance": 1.2, ... }
```

The card markup contains no distance element at all. Results *are* sorted by distance, so a user sees an ordering they have no way to explain.

**This is a regression.** The build released to `release-iteration-1` showed a distance badge on each card; the current `dev` build does not.

**Owner:** Frontend · **Effort:** minutes — the value is already in the response.

### F-2 · The reference point is not shown — **HIGH**

AC1.1.3 exists for a real reason: a suburb is an area, not a point, so a distance is meaningless without saying what it was measured from.

The API already returns exactly the right string:

```json
"reference_point": { "label": "the centre of Carlton 3053",
                     "latitude": -37.795471, "longitude": 144.961432 }
```

The results header shows *"Cricket venues near Carlton 3053"* and drops the label entirely.

**Owner:** Frontend · **Effort:** one line of JSX.

### F-3 · Unrecognised location message — **MEDIUM**

Searching `Sydney`, `Geelong`, `Zzzznotaplace` and `9999` each returns:

```
No suburb or postcode matching 'Sydney'.
```

Correct and honest, and importantly **not** a bare empty list. But AC1.1.4 asks the message to either name the area currently covered or offer the closest matches, and it does neither.

Two further observations:

- **Stale results stay on screen** beneath the error, which reads as though the search partly worked.
- The API returns HTTP 422 `unknown_place`, so the frontend has everything it needs to say something better.

Suggested copy: *"We currently cover the City of Melbourne. Try Carlton, Docklands or Parkville."*

**Owner:** Frontend (copy) · **Effort:** small.

### F-4 · Result count does not update on filter change — **MEDIUM**

Ticking **Step-free transport stop** leaves the header reading `10 venues found` until Search is pressed. After pressing Search it correctly becomes `0 of 10 venues found`.

The `aria-live="polite"` region is already in place, so this is about *when the fetch fires*, not about announcing the change.

**Owner:** Frontend · **Effort:** small — trigger the search on filter change.

### F-5 · No provenance in search results — **MEDIUM**

AC1.3.2 requires "the name of the source that recorded it". The search response omits it:

```json
"amenities": { "toilet": { "state": "recorded", "distance": 216 } }
```

`/api/v1/venues/{id}` **does** carry source information, so the data exists — it is simply not in the search payload.

**Owner:** Backend first (add to `SearchOut`), then Frontend to render it.

### F-6 · Missing favicon — **LOW**

```
GET /favicon.svg → 403
```

On every page load. `index.html` references it; it is not in the bundle. S3 returns 403 rather than 404 for a missing object behind Origin Access Control.

**Owner:** Frontend · **Effort:** add the file to `frontend/public/`, or drop the `<link>`.

### F-7 · Page title is `frontend` — **LOW**

Vite's scaffold default, still in `frontend/index.html`. This is the browser-tab text during the demo and in any screenshot.

**Owner:** Frontend · **Effort:** one line. Suggest *"SportAble Melbourne"*.

---

## What is working well

Worth recording, because it is easy to read a defect list and conclude the build is weak. It is not.

- **Mobile layout is clean.** At 390×844 there is **no horizontal scroll** and **no element overflows the viewport**. This is the thing most likely to be broken at this stage, and it is not.
- **Accessibility fundamentals are sound.** `lang="en"`; no unlabelled inputs; no images missing `alt`; the distance bands are real `<input type="radio">` with accessible names; a sensible heading outline; decorative icons hidden from screen readers; status conveyed by symbol and text rather than colour.
- **AC1.2.3 is the best-implemented criterion in the build.** Undocumented venues are grouped, counted and collapsible, with actionable guidance. Grouping rather than dropping is what the product is *for*, and it was the hardest criterion to get right.
- **AC1.3.3 holds exactly.** Transport reads *"No published information — check with the venue"* because DS-03 has no transformer yet. That is the correct, honest output — an absent dataset is reported as unknown, never as absent.
- **Performance is comfortable.** Worst observed round trip 1.05 s against a 3 s budget, through CloudFront to a Lambda in a private subnet.

---

## Recommended order of work

| # | Item | Owner | Why first |
|---|---|---|---|
| 1 | **F-1** venue distance | Frontend | Visible AC; data already returned |
| 2 | **F-2** reference point | Frontend | Visible AC; one line |
| 3 | **F-7** page title, **F-6** favicon | Frontend | Ten minutes total, and the first things anyone sees |
| 4 | **F-4** live count | Frontend | Behavioural AC |
| 5 | **F-3** location message | Frontend | Copy plus clearing stale results |
| 6 | **F-5** provenance | Backend, then Frontend | Needs an API change first |

Items 1–3 together are under an hour and move three criteria from partial or fail to pass.

---

## Operational risk for the demo

**The database must be running or every search fails.**

`sportable-staging-db` is stopped outside working hours to control cost. The deploy smoke test checks `/health`, `/config` and the SPA — **none of which touch the database** — so a deploy goes green with the database stopped while every search returns 500.

Two mitigations, either is enough:

- Add "start RDS" to the demo checklist, and start it well before, since it takes 5–8 minutes to become available.
- Add a search call to the deploy smoke test so a stopped database fails the deploy loudly.

```bash
export AWS_PROFILE=sportable
aws rds start-db-instance --db-instance-identifier sportable-staging-db
aws rds wait db-instance-available --db-instance-identifier sportable-staging-db
```

---

## Notes on method

All testing was **read-only**. No data was written, no configuration changed, no deploy triggered.

Checks were made against observable behaviour rather than source code: DOM inspection, rendered text, computed layout at two viewports, `aria` attributes, console output, and direct API calls from the page's own origin. Where the report claims something is missing, it was confirmed absent from the rendered markup, not inferred from reading the component.
