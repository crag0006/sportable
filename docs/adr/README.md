# Architecture Decision Records

A short record of each decision that was hard to make and would be expensive to
reverse. Context, the options weighed, what was chosen, and what it cost.

**Why these exist.** In week nine someone — a marker, a teammate, or you —
will look at something here and ask *"why is it like this?"* These answer that
in the repository rather than in someone's memory of a chat thread.

| | Decision | Status | Recorded |
|---|---|---|---|
| [ADR-001](ADR-001-terraform-over-cdk-and-sam.md) | Terraform, not AWS CDK or SAM | Accepted | 1 Sep 2026 |
| [ADR-002](ADR-002-gateway-endpoint-over-nat.md) | An S3 Gateway Endpoint instead of a NAT Gateway | Accepted | 1 Sep 2026 |
| ADR-003 | The path between a starting point and a venue | **Not yet written** | — |

## ADR-003 is outstanding, and it blocks other people

US2.2 and US2.3 both need a path between the user's starting point and the
venue, and nobody has decided where that path comes from. §4.2 of the Epics
document flags it as a dependency to settle early, because it changes what the
Frontend team is able to draw.

There is also an infrastructure constraint on it that is easy to miss: **map
tiles and routing are different problems.** OpenStreetMap tiles are fetched by
the browser and cost us nothing. Computing a walking route is a separate
service, and if it were called from our API it would need outbound internet from
inside the VPC — which [ADR-002](ADR-002-gateway-endpoint-over-nat.md)
deliberately does not provide.

That leaves two viable shapes: a straight-line corridor computed in PostGIS, or
routing done client-side in the browser with the resulting path posted to our
API. Both are free. Writing it up is deferred by decision, not oversight.

## Writing a new one

Copy the shape of ADR-002 — it is the better example of the two, because its
consequences section is honest about what the decision broke.

- **Number them in order and never renumber.** A superseded ADR stays, with its
  status changed and a link forward. The history is the point.
- **Record the date decided and the date written**, especially when they differ.
  ADR-001's decisive argument was discovered a week after the decision.
- **Write the consequences you did not want**, not only the benefits. An ADR
  that only lists advantages is advocacy, not a record.
- **Cite figures with their source and date.** ADR-002 corrects two cost
  estimates that were wrong for a year's worth of copy-paste, because nobody had
  checked which region they were for.
