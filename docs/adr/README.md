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
| [ADR-003](ADR-003-straight-line-corridor-over-routing.md) | A straight-line corridor, not a route | Accepted | 15 Sep 2026 |
| [ADR-004](ADR-004-victorian-scope-over-greater-melbourne.md) | Victorian scope for every source, on a column still named `in_greater_melbourne` | Accepted — already in effect | 15 Sep 2026 |
| [ADR-005](ADR-005-aaa-play-over-playhq.md) | AAA Play as the events source, not PlayHQ | Accepted | 15 Sep 2026 |
| [ADR-006](ADR-006-provider-claims-are-not-confirmed.md) | An AAA Play facility claim never produces a `confirmed` status | **Proposed** — the build enforces it; task D5 says otherwise | 15 Sep 2026 |

## Two of these are not settled, and both block other people

**ADR-006 is the one to read first.** The build refuses to turn an AAA Play
`true` into a `confirmed` facility status, and task D5 of the Iteration 2
document says it should. D5, D7, D8 and D9 all depend on which way that goes,
so building them before it is settled wastes more than the discussion costs.
Either the document changes or the build does; it should not be settled in a
commit message.

**ADR-004 records something that already happened.** The spatial clip widened
from the 31 Greater Melbourne councils to the whole of Victoria on
14 September 2026, by repurposing the column task D2 explicitly said not to
repurpose. Venues went from 129 to 3,896, so the Epic 1 venue search does not
return what it returned before. The ADR states the trade honestly and the team
still owes an answer on whether to absorb it or back it out.

ADR-003 was flagged as outstanding here through Iteration 1 and is now written.
The infrastructure constraint behind it is still worth knowing, because it is
easy to miss: **map tiles and routing are different problems.** OpenStreetMap
tiles are fetched by the browser and cost us nothing. Computing a walking route
is a separate service, and if it were called from our API it would need outbound
internet from inside the VPC — which
[ADR-002](ADR-002-gateway-endpoint-over-nat.md) deliberately does not provide.

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
