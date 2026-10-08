# ADR-004 — Victorian scope for every source, on a column still named `in_greater_melbourne`

| | |
|---|---|
| **Status** | Accepted — **already in effect**, not proposed |
| **Date decided** | 14 September 2026 — the date the scope change landed |
| **Date recorded** | 15 September 2026 |
| **Decider** | Data engineering, during the DS-07/DS-08 load. Not minuted at the time; this ADR is the record |
| **Affects** | Every source in the register, the Epic 1 and 2 venue search, and the meaning of one column name |

---

## This describes something that happened

Read the rest of this as a record, not a proposal. The scope change shipped on
14 September 2026, the DS-07/DS-08 load ran under it, and every venue in the
database today is there because of it. Nothing below is waiting on approval. The
only thing still open is whether the task document absorbs it or the build backs
it out — see *The disagreement*, below.

## Context

Epic 4 is titled *"Sports Events Across **Victoria**"*. The loader was not
statewide. It clipped every source to the union of the **31 Greater Melbourne
councils**, and `lga.in_greater_melbourne` was the flag that drove the clip.

AAA Play spans **17 regions**, including Mallee, Wimmera, Gippsland and East
Gippsland. Clipping it to Greater Melbourne would have discarded a large share
of the 532 activities and contradicted the epic statement on the title line.

Task **D2** of the Iteration 2 document set out the intended fix, and was
explicit about how *not* to do it:

> Add `in_victoria` to `lga` — derived from DS-06's `STE_CODE21 = 2`, alongside
> the existing `in_greater_melbourne`. **Do not repurpose the existing column;
> the Epic 1 and 2 venue search still depends on it.**

## What was built instead

`in_victoria` was not added. The existing column was repurposed.

**1. The default scope became the empty set, and empty means everything.**

```python
DEFAULT_SCOPE: set[str] = set()
```

An empty set flags every Victorian council in the DS-06 layer. The reasoning is
in the file, and it is a good reason: a hard-coded list of roughly eighty names
*"would go stale the next time the ABS renames a council, and it would go stale
silently, by quietly dropping that council's venues."* An empty default cannot
go stale.

**2. `VIC_BBOX` widened to the state extremes** — 140.90 to 150.05 longitude,
−39.25 to −33.95 latitude: the South Australian border in the west, Cape Howe in
the east, Wilsons Promontory in the south, the Murray in the north. `GM_BBOX` is
kept as an alias so six notebooks do not break at once.

**3. The column kept its name and changed its meaning.** `in_greater_melbourne`
now means *in scope*. Nothing reads the name; everything reads the flag.

**4. Scope is read from the database, not from a constant.** `DS-06` sets the
flag and takes `--scope` directly; every other source reads
`scope_from_database(conn)`. One definition of scope, and a load run cannot
disagree with the boundaries already in the table.

### What the load actually reported

| | |
|---|---:|
| Victorian postcodes flagged `t` | **733** |
| Interstate postcodes flagged `f` | **1,908** |
| Suburbs flagged `t` | **2,944** (all) |
| Venues before → after | **129 → 3,896** |

## The trade-off, honestly

**Renaming the column would have been correct and was not worth it.**
`in_greater_melbourne` appears in `001_schema.sql`, in `005_read_model.sql`, in
the loader, in the orchestrator and in the backend repository layer. Renaming it
touches the read model, the API and the frontend, and buys **no behavioural
change whatsoever** — the same rows come back either way. On a nine-week project
that is a poor use of a day.

**And the column name now lies about what it holds.** A column called
`in_greater_melbourne` that is `true` for Mildura is a trap for the next person
who reads the schema without reading the comment. The comment in `load_run.py`
is currently the only thing standing between that name and a wrong assumption,
and comments do not travel with a column into a query someone writes in `psql`.

Both of those are true at once. The decision is that the misleading name is the
cheaper of the two costs, and this ADR is the mitigation.

### The disagreement

D2 said not to do this, and it was done. D2's stated risk — *"the Epic 1 and 2
venue search still depends on it"* — **was realised rather than avoided**:
venues went from 129 to 3,896, so Epic 1 venue search does not return what it
returned before. D2's own done-when clause (*"an Epic 1 venue search returns
exactly what it returned before"*) is therefore not satisfied and cannot be.

That is a scope change that already shipped, not a defect. Either the task
document absorbs it, or the build adds `in_victoria` and narrows
`in_greater_melbourne` back to the 31 councils. It should not be settled in a
commit message.

## Consequences

### Regional coverage is now first class, and the evidence around it is thinner

Roughly 213 of the 530 activities and 215 of the 552 facilities on the
11 September pull sit outside Greater Melbourne, led by Geelong, Bendigo and
Ballarat. Under the old scope they were out of area. They are in scope now and
carry the same obligations as anything metropolitan.

**The consequence to state plainly: DS-04 accessible parking is published by the
City of Melbourne, for its own area only.** A venue anywhere else in Victoria
therefore carries **no parking record at all**, and the product shows that as
*"no published information"* — never as an absence of parking. The further a
programme sits from the City of Melbourne, the fewer of the four facility tiles
can say anything. DS-03 transit coverage falls away outside the network for the
same reason.

This is the existing honest gap widening, not a new defect. But it is now the
normal case for a regional programme rather than the exception, and two rules
follow from it: **nothing may be padded to hide the difference, and no regional
programme may be filtered out to make the coverage look even.**

### `--scope` narrows everything, not just venues

Every source is clipped against the union of the flagged polygons. Narrowing
scope for one load silently changes what "in scope" means for toilets and
parking as well as for venues. Narrow it with `--scope` on a DS-06 load,
deliberately, and never by editing `DEFAULT_SCOPE`. The runbook says the same
thing next to the command.

### AAA Play's LGA junk terms matter more than they did

The publisher's `lga` taxonomy carries about 25 zero-count junk terms, mostly
bare lowercase council names. Under the 31-council scope a stray term like
`benalla` fell outside the boundary anyway. Benalla is in scope now, so a
term-based filter would quietly disagree with the polygon. Scope stays decided
by point-in-polygon against DS-06, as it is for every other source; the
publisher's terms are a cross-check and a label, never a boundary.

### One field stays null on purpose

`coverage.records_in_target_area` on the DS-09 card is still `null`, and the
card explains why: *"no records fall outside Victoria"* is an assumption about a
publisher's coverage, not something anyone has counted. Re-profile
`rows_outside_scope` from a real DS-09 load before filling it in.

## Revisit when

- Someone writes a query against `in_greater_melbourne` expecting Greater
  Melbourne. That is the failure this ADR exists to make survivable, and it is
  also the signal that the rename is finally worth the day.
- A screen needs a genuine metropolitan/regional split. The publisher's own
  region taxonomy gives a Greater Melbourne cut — 317 activities against 337
  facilities — which is useful for a profiling comparison. It is **not** a scope
  boundary and must never be used as one on screen. The 31-council list is kept
  in `data/notebooks/profile_lib.py` for exactly that purpose.
- DS-04 gains a second publishing council, at which point the parking gap
  narrows and the wording on the regional venue cards should be re-read.

## See also

- [ADR-005](ADR-005-aaa-play-over-playhq.md) — the source that forced the scope question
- [ADR-006](ADR-006-provider-claims-are-not-confirmed.md) — why a regional venue with no parking record says "no published information"
- `data/scripts/load_run.py` — `DEFAULT_SCOPE`, and the comment that is currently the only warning about the column name
- `data/notebooks/profile_lib.py` — `VIC_BBOX`, and the 31-council list kept for profiling only
- `data/sources/DS-09_aaaplay.yaml` — `coverage.notes`, on what statewide scope changed
