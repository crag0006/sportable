# ADR-003 — A straight-line corridor, not a route

| | |
|---|---|
| **Status** | Accepted |
| **Date decided** | 2 September 2026 — the date `006_route_corridor.sql` landed |
| **Date recorded** | 15 September 2026 |
| **Decider** | Charan — Infrastructure / Platform |
| **Affects** | US2.2, US2.3, AC2.3.4, AC4.2.4, and the wording on every directions screen |

---

## Context

US2.2 and US2.3 both need a path between a starting point the user supplies and
a venue, with the accessible facilities along it. The
[ADR index](README.md) recorded this as outstanding on 1 September 2026 and
noted, correctly, that it blocks the Frontend team because it changes what they
are able to draw.

Two constraints narrowed it before any preference did:

- **Nothing inside the VPC can reach anything outside it.**
  [ADR-002](ADR-002-gateway-endpoint-over-nat.md) deliberately left the private
  route table without a `0.0.0.0/0` entry. A routing call made from our API
  would not fail — it would hang, then time out at ten seconds, which is the
  same failure that already turned a Parameter Store read into a 500.
- **The path depends on a value supplied at request time.** Every other status
  in the product is derived once in the pipeline and read back. A corridor
  cannot be, because the origin is not known until someone types it.

There is also a privacy position already on the record. DS-05-D1 permits a
coordinate pair to leave our account and nothing else, and its controls include
*"no persistence"* — route geometry, origin and destination are held for the
length of one request and never written to the database, to object storage or to
application logs.

## Options considered

| Option | What it is | Cost |
|---|---|---|
| **Straight-line corridor in PostGIS** | `ST_MakeLine(origin, venue)`, then amenities within a band of that segment | $0. No outbound call, no quota, no key |
| **Client-side routing, path posted to our API** | The browser calls openrouteservice, sends the LineString back, we run the same corridor query over it | $0, but a browser dependency, a per-person quota, and a third-party call on the hot path |
| ~~Routing from inside the VPC~~ | Our API calls openrouteservice directly | A NAT Gateway at **$43.07/month** ([ADR-002](ADR-002-gateway-endpoint-over-nat.md)), or an interface endpoint that still cannot reach a non-AWS host. Disqualifying |

## Decision

**A straight-line corridor, computed in PostGIS at request time, and labelled as
a straight line everywhere it is shown.**

`GET /venues/{id}/corridor` is the whole feature.
`GET /venues/{id}/directions` exists, is in the schema, and returns
`404 not_implemented` pointing at the corridor endpoint. It is reserved for the
routed journey, not pretending to be one.

### What the approximation actually is

Four things, and all four are visible in the response rather than buried:

**1. The path is one segment between two points.**

```sql
ST_MakeLine(
    ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat), :srid),
    ST_SetSRID(ST_MakePoint(:venue_lon,  :venue_lat),  :srid)
)
```

`path.kind` is the literal `"straight_line"`, `path.coordinates` holds exactly
two entries, and `path.length_m` is the haversine distance between them —
commented in the schema as *"straight-line metres, NOT a travel distance"*.

**2. Membership is perpendicular distance, not detour distance.**
`ST_DWithin(a.geom::geography, line::geography, within_m)`. A facility reported
as 90 m from the path is 90 m from the *line*. Nobody has checked whether you
can get to it from the footpath, or whether a freeway sits between the two.

**3. Order is order along the line, not order encountered.**
`ST_LineLocatePoint` gives a fraction from 0 at the origin to 1 at the venue,
and `along_path_m` is that fraction multiplied by the straight-line length.

**4. The band is 400 m by default**, taken from `corridor_default_m`, and only
the bands published at `/api/v1/config` are accepted — a request for 300 m is a
`422 invalid_distance_band` rather than a silently different answer.

### Why this, for this project

- **It costs nothing and adds no failure mode on the request path.** No key, no
  quota, no rate limit, no provider outage. The corridor cannot degrade, because
  there is nothing for it to degrade from.
- **It keeps the privacy control structural rather than procedural.** The
  corridor functions take geometry as an argument and return rows. There is no
  insert path, so "we do not store the journey" is a property of the code shape
  and not a rule someone has to remember.
- **The database work is the same either way.** `006_route_corridor.sql` takes
  `route geometry` — any line. The straight segment and a real routed LineString
  go through the identical predicate. Choosing the cheap path now costs nothing
  later, because the expensive path reuses it unchanged.

## Consequences

### The one that matters: this is not a route, and the interface must never say it is

That is not a caveat, it is the acceptance criterion. AC2.3.4 requires the
interface to state what was and was not verified, and the DS-05 card says the
sentence *"must be built from the profile's actual restriction parameters, not
from a plausible-sounding description."* The same applies with more force to a
straight line, which verifies nothing about a path at all.

So the response carries the claim in three separate places, and a test asserts
the word never appears:

```python
assert "route" not in joined  # AC2.3.4: never described as a route
```

- **`disclaimer`** — *"This is a straight-line corridor, not a route. Nothing
  here confirms that any path is step-free."*
- **`checked`** — one sentence naming exactly what was looked at: the facility
  types found *"recorded in published datasets within {within_m} m of a straight
  line from {origin} to {venue}"*.
- **`not_checked`** — *"Whether any path between these points is step-free. No
  dataset records kerb ramps, gradients or crossings."*, plus every facility type
  with no dataset loaded, plus whether anything is open or unlocked when you
  travel.

The venue page's limits section makes the same admission about distance
generally: *"Distances are straight-line, not a checked path."*

### Absence of a facility and absence of a dataset are different answers

`types[].status` is three-valued — `found`, `none_within`, `no_data` — and each
gets different copy. "No accessible toilets recorded within 400 m of this line"
and "No published information loaded for accessible transport stops" must never
read the same. Accessible transport is `no_data` today, because DS-03 still has
no transformer. An unknown is never a no.

### What we accepted by not routing

- A facility inside the band may be unreachable — the wrong side of a river, a
  rail line or a freeway. The corridor cannot tell.
- The sequence numbers are travel order along a line nobody walks.
- The straight-line length is shorter than any real journey, always.

None of these is fixable by widening the band. They are fixable only by routing,
and the honest response until then is to say so on the screen.

### What it means for AC2.3.4 and AC4.2.4

**AC2.3.4** — the wording must describe the straight-line corridor. Not "the
route to the venue", not "facilities along your route". *"Facilities recorded
within 400 m of a straight line between your starting point and the venue"* is
what was checked, so that is what the criterion has to say.

**AC4.2.4** is AC2.3's requirement pointed at an event instead of a venue, so it
inherits this ADR exactly. Task I6 in the Iteration 2 document lists *"carry
ADR-003's straight-line corridor approximation forward, or supersede it"* — and
the decision rule is the same either way: **the AC must describe what was
actually checked on the day it is demonstrated.** If Iteration 2 ships the
routed corridor, AC4.2.4 says "route" and this ADR is superseded. If it does
not, AC4.2.4 says "straight line" and no screen in the events epic may use the
word route either.

## Revisit when

I6 lands the routed corridor. Three things are already in place for it and are
worth knowing before anyone re-plans the work:

- **The SQL needs no change.** `route_corridor` and `route_corridor_summary`
  accept an arbitrary geometry. Only the caller changes.
- **The response shape needs no change.** `CorridorPathOut.kind` is already
  `Literal["straight_line", "routed"]`.
- **The SRID question is already settled, and recorded in `006` rather than
  buried in the API.** openrouteservice returns EPSG:4326; the serving store is
  EPSG:7844. `ST_Transform` between them needs grid files that are not installed
  on RDS, so the caller declares the geometry as 7844 instead. The two differ by
  roughly 1.8 m at Melbourne latitudes, and 1.8 m cannot change membership of a
  400 m corridor. That is a second deliberate approximation, it is fine for a
  corridor, and it would not be fine for anything reporting a position to
  sub-metre precision. Nothing here does.

When it lands, change this ADR's status, link forward, and change the
disclaimer, the `checked` sentence and the two acceptance criteria **in the same
change**. A routed corridor shipping while the copy still says "straight line"
is the same class of error as the reverse, and it is the one that would go
unnoticed.

## See also

- [ADR-002](ADR-002-gateway-endpoint-over-nat.md) — why a routing call cannot be made from inside the VPC
- `data/sql/006_route_corridor.sql` — the two functions, and the SRID note
- `data/sources/DS-05_openrouteservice.yaml` — DS-05-D1, and the no-persist control
- `backend/app/repositories/postgres.py` — `SQL_CORRIDOR`, the straight-line caller
- `backend/app/domain/presenters.py` — `corridor_out`, and the three places the claim is made
