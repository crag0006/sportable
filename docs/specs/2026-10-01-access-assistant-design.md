# Access Assistant — Iteration 3 Design

**SportAble Melbourne** · Team Lumera · FIT5120 2026 S2
Status: **draft for team review** · Written 1 October 2026 · Revised 2 October 2026
Owner: Charan Kumar Raghupatruni (infrastructure, data)

> **Revision 2 October:** adds Epic C, retrieval over our own free text, with
> `pgvector` in the existing database. This is the first part of the product
> that generates prose rather than assembling it from templates, so §4 gains a
> fourth correctness rule and §6 gains a schema change. Epics A and B are
> unchanged and remain template-only.

---

## 1. Purpose

Iteration 3 adds one feature in two input modes — a text chatbot and a voice
assistant — answering questions about venues, events and what to expect at a
programme, from data the product already holds.

The feature exists for a reason the rest of the product is built around. Nearly
every attribute SportAble publishes is a *proximity* attribute: what is near a
venue, not what is inside it. No open dataset records step-free entry, doorway
widths or courtside access, and 135 of 191 sampled programmes (71%) run at
places absent from the government venue register. A conversational interface
invites exactly the questions the structured data cannot answer.

Two responses, and they are the two halves of this iteration's value:

1. **When nobody has published the answer, hand over** — say so plainly and
   produce the questions worth asking, with the number or registration link.
2. **When the answer is in prose rather than in a column, go and find it.** The
   publishers write 280 KB of free text we currently store and never read:
   what to bring, whether a carer can come, whether the first session is free,
   whether beginners are welcome. That is the Epic C corpus.

---

## 2. What this iteration does, and what it does not

This section is the scope contract. If something is not listed under "does", it
is out, including things that would be easy to add.

### 2.1 What the assistant does

| # | Capability | Epic |
|---|---|---|
| C1 | Answers venue discovery questions in plain language | A |
| C2 | Answers event discovery questions in plain language | A |
| C3 | Shows its interpretation first, editable before results | A |
| C4 | Hands over when nothing is published: questions, phone, registration link | B |
| C5 | Answers "what should I expect / what do I bring" from publisher free text, with the source sentence quoted | C |
| C6 | Refuses out-of-scope questions, with no model call | A |
| C7 | Works by voice as well as text: same intents, spoken answers, on-screen transcript | A, B, C |
| C8 | Falls back to the existing filter UI on any failure | A |

### 2.2 What the assistant does **not** do

- **Does not write prose about venues or events in Epics A and B.** Discovery
  and handover answers are assembled from templates over returned records.
  Generation exists only in Epic C, only over retrieved text, and only with a
  quoted source sentence (see R4).
- **Does not answer general sport questions.** No game rules, no how-to-play,
  no coaching, no health or funding advice. If a publisher wrote it about their
  own programme, we can quote it; otherwise the question is refused.
- **Does not ingest third-party rulebooks or instructional content.** See §2.5.
- **Does not take bookings or any personal details.** It links out.
- **Does not remember a previous session.** State lives in the tab.
- **Does not accept user-submitted content.** No write path from a browser.
- **Does not plan journeys** (ADR-003), or infer new structured attributes from
  venue text — the inferred-signals feature stays on the backlog.
- **Does not use voice as an identifier**, record audio, or offer a wake word.
- **Does not run voice as the only path.** Keyboard parity always.

### 2.3 Epic C in one line

Retrieval over **our own already-ingested publisher text**, so the assistant can
answer "what is this programme actually like" — grounded, quoted and cited, and
never extended to content we do not hold.

### 2.4 Explicitly deferred

The council coverage view (Epic 6) is deferred to the backlog, so that the
assistant can ship in both modes with retrieval. Recorded here rather than
quietly dropped; the report should state it.

### 2.5 Considered and rejected: a game-rules corpus

Loading public rulebooks — how to play pickleball, the rules of boccia — was
considered and rejected for four reasons, recorded so the decision is not
relitigated mid-iteration.

1. **Licensing.** Official rulebooks are copyrighted, not open. The project
   constraint is Australian open data only, with a licence recorded per source.
2. **Off-thesis.** The product answers "can I get in and play here". Rules are
   published well already by governing bodies; neither persona's problem is
   rules.
3. **It would undo the safety property.** Epics A and B generate nothing. A
   rules corpus means open-ended generation over content we cannot validate
   against a record.
4. **It would harm our primary users.** Asked "how do I play wheelchair
   basketball", a general corpus returns able-bodied basketball. The database
   already carries `sport_crosswalk_adaptive_is_never_folded` to stop Boccia
   being pointed at Bowls; a general rules corpus would violate at the content
   layer the rule enforced at the schema layer.

If introductory adaptive-sport content is wanted later, it must come from
sources that are openly licensed or that have given written permission, and
carry per-chunk provenance like any other source.

---

## 3. Architecture

### 3.1 The pipeline

```
speech ──► browser STT ──┐
                         ├─► Bedrock Haiku 4.5 ─► intent + slots (JSON)
keyboard ────────────────┘                             │
                                   ┌───────────────────┴───────────────────┐
                                   ▼                                       ▼
                        structured retrieval                      vector retrieval
                     (repository / read model)                (pgvector over chunks)
                                   │                                       │
                                   ▼                                       ▼
                        templated answer  (A, B)        grounded answer + quote  (C)
                                   └───────────────┬───────────────────────┘
                                                   ▼
                                       screen  ·  speech (voice mode)
```

The intent classifier decides which retrieval path runs. Discovery and handover
never reach the generative path.

### 3.2 Components

| Component | Where | Notes |
|---|---|---|
| Assistant Lambda | Private subnet A | Queries PostgreSQL directly via the existing repository |
| Bedrock — `anthropic.claude-haiku-4-5` | ap-southeast-2 | Intent and slot extraction; Epic C answer composition |
| Bedrock — `amazon.titan-embed-text-v2:0` | ap-southeast-2 | Embeddings, at ingest and per query. Confirmed available in Sydney |
| Bedrock VPC interface endpoint | Private subnet A, one AZ | ~USD $7.30/month; the subnet has no other route out |
| `pgvector` | Existing RDS instance | No new service. Corpus is ~900 chunks, a few MB |
| Speech to text / text to speech | The user's browser | Web Speech API; no audio leaves the device |

### 3.3 Why `pgvector` and not a managed vector service

The corpus is roughly 280 KB of text, about 900 chunks after splitting. That is
a few megabytes of vectors — well inside what Postgres handles with an HNSW
index, in the instance we already run and already back up. OpenSearch Serverless
or a third-party vector database would add cost, a second datastore to keep in
step with the pipeline, and a second thing to explain. Embedding the whole
corpus costs a fraction of a cent per rebuild.

### 3.4 Infrastructure changes

1. `aws_vpc_endpoint` for `bedrock-runtime`, interface type, **subnet A only** —
   pricing is per AZ and the Lambdas run in one subnet.
2. **Private DNS enabled**, or boto3 resolves the public hostname and the call
   hangs rather than failing.
3. Endpoint security group permitting 443 from the Lambda security group, and a
   **new egress rule on the Lambda security group** to reach it. That group
   currently permits exactly two destinations: 5432 to the database and 443 to
   the S3 prefix list.
4. `CREATE EXTENSION vector` on the RDS instance.
5. `bedrock:InvokeModel` on the execution role for both model IDs — **blocked on
   the account holder, see §10.1.**

---

## 4. The four correctness rules

Each is a way this feature could mislead someone into a wasted trip, which is
the harm the product exists to prevent. Each is an acceptance criterion with a
test.

**R1 — A recurring programme is never given a date.**
Programmes carry weekdays and a time of day; only fixtures carry `starts_at`.
The assistant says "Tuesdays, mornings, as published". Relative phrases such as
"this weekend" are resolved to weekday values by code, never by the model.

**R2 — A missing attribute is never rendered as "no".**
`program_venue_attribute` stores only what a provider ticked yes; the source
form has no null state, so absence means *not published*. Two honest answers
exist: "the provider says yes" and "nobody has published that". Never "no".

This mirrors ADR-006, which is **still Proposed, not ratified by the team**, and
which records a conflict with task D5. R2 is written here as a hard rule
regardless: the assistant states these things in sentences rather than status
chips, and a spoken "no" is harder to qualify. If the team settles ADR-006 the
other way, this rule must be revisited before the assistant ships.

**R3 — An unmatched place never shows or implies venue accessibility.**
135 of 191 sampled programmes (71%) run at places with no match in the
government register. For those, the assistant has the publisher's own address
and nothing about toilets, parking or transport.

**R4 — A generated sentence quotes its source, or it is not shown.** *(new, Epic C)*
Every claim in an Epic C answer must be supported by a retrieved chunk, and the
answer displays the source sentence and the programme it came from. An answer
containing an unsupported claim is discarded whole and the retrieved text shown
on its own. The user must always be able to see what the provider actually
wrote, not only our paraphrase of it.

---

## 5. Epics, stories and acceptance criteria

### Epic A — Conversational discovery

*As a wheelchair user or carer, I want to ask in my own words, so that I do not
have to work out which filters match my needs.*

**US-A1 — Ask for venues in plain language**
- AC-A1.1 The interpretation is displayed as editable chips before any result.
- AC-A1.2 Editing a chip re-runs the search from the chips, not the sentence.
- AC-A1.3 A named facility sets the corresponding filter, visibly.
- AC-A1.4 Results use the existing venue card, with unchanged provenance.

**US-A2 — Ask for events in plain language**
- AC-A2.1 Extracts any of: sport, suburb, distance band, weekday, time of day,
  price, age range, access need.
- AC-A2.2 Publisher wording resolves through `sport_crosswalk` — "Ability Hoops"
  finds Basketball.
- AC-A2.3 No calendar date is ever reported for a programme (**R1**).
- AC-A2.4 Where the place did not match a venue, the response says venue
  accessibility is unknown (**R3**).
- AC-A2.5 An access need outside the vocabulary produces a handover, not an
  empty result.

**US-A3 — Be refused clearly when out of scope**
- AC-A3.1 Out-of-scope questions return the capability message **with no model
  invocation**.
- AC-A3.2 The message names what the assistant can do, in one sentence.

### Epic B — Guided handover

*As a wheelchair user, I want the questions worth asking, so that one phone call
answers everything instead of three.*

**US-B1 — Be told what to ask**
- AC-B1.1 A question about an unpublished attribute returns a plain statement
  that it is not published, and why.
- AC-B1.2 The response includes the call-ahead question list for the selected
  sport, ordered by consequence.
- AC-B1.3 Venue: phone number where published. Event: provider name and
  registration link.
- AC-B1.4 The list is readable offline once rendered, and printable.

### Epic C — Retrieval over publisher text

*As someone deciding whether to turn up, I want to know what the session is
actually like, so that I am not relying on a title and a weekday.*

**US-C1 — Ask what to expect at a programme**
- AC-C1.1 Questions such as "what do I bring", "can my support worker come",
  "is it suitable for a beginner", "is the first session free" are answered from
  the retrieved programme description.
- AC-C1.2 Every answer displays the quoted source sentence and the programme and
  provider it came from (**R4**).
- AC-C1.3 Where retrieval finds nothing above the relevance floor, the assistant
  says so and hands over to Epic B rather than generating.
- AC-C1.4 The answer never states an access *status*; those come only from the
  structured path (**R2**, **R3**).
- AC-C1.5 Retrieval is restricted to the chunks of programmes already in the
  result set under discussion, so an answer cannot quote an unrelated provider.

**US-C2 — See the provider's own words**
- AC-C2.1 The full description is reachable in one action from any Epic C answer.
- AC-C2.2 The quoted sentence is highlighted within it.

### Epic A/B/C — voice mode

**US-V1 — Ask by voice**
- AC-V1.1 Every intent in Epics A, B and C is reachable by voice; voice adds no
  intent of its own.
- AC-V1.2 Recognised text is displayed and confirmed before the search runs.
- AC-V1.3 A spoken answer gives a count and at most two items, then directs to
  the screen.
- AC-V1.4 An Epic C spoken answer reads the paraphrase and names the provider;
  the quoted sentence is on screen (see §8.3).
- AC-V1.5 A transcript of every question and answer stays on screen.
- AC-V1.6 Microphone denied, unsupported browser or recognition failure falls
  back to text, never a dead end.
- AC-V1.7 No audio is transmitted off the device or persisted.

---

## 6. Data workstream

The assistant understands only what the vocabularies contain, and can only
retrieve what has been chunked and embedded. This is on the critical path.

### 6.1 Controlled vocabularies — the extraction target

From 191 live programmes, 1 October 2026. These are the exact values the slot
extractor must target.

| Slot | Values |
|---|---|
| `access_needs` (12) | Auslan · Autistic or neurodivergent · Blind or vision impaired · Deaf or hearing impaired · Disability specific · Immunocompromised · Intellectual disability · Open to everyone · Physical limitation · Psycho-social · Sensory friendly · Wheelchair accessible |
| `age_ranges` (6) | Child (0-4) · Child (5-12) · Youth (13-17) · Youth (18-25) · Adults (26+) · Older Adults (55+) |
| `time_of_day` (6) | morning · afternoon · evening · after_school · all_day · school_holiday_program |
| `weekdays` (7) | monday … sunday |
| `price` (2) | free · paid |
| `sport` | 49 current values, via the 84-row crosswalk |

### 6.2 The Epic C corpus, measured

| | |
|---|---|
| Source | `program.description`, DS-09 |
| Coverage | 160 of 160 sampled programmes carry one; 521 programmes loaded |
| Size | mean 543 characters, max 2,217 · ≈280 KB total |
| Expected chunks | ≈900 at ~500 characters with overlap |
| Vector storage | ≈4 MB at 1024 dimensions |
| Embedding cost | well under one cent per full rebuild |

Content check — the corpus answers the practical questions: "bring" appears in
28 of 160, "equipment" 15, "carer" 12, "beginner" 10, "no experience" 6,
"support worker" 5, "parking" 5. It does **not** answer game rules ("rules" 2,
"how to play" 1), which is consistent with §2.5.

**Venue free text is a second, thinner corpus** — `changeroom_description`,
amenity `access_note` and `facility_note`. Its population has **not been
measured** and must be before it is committed to; most long strings in the API
response are sentences the product generates, and embedding our own output
would be circular. Programme descriptions alone are sufficient for Epic C.

### 6.3 D1 — Gold evaluation set *(Epics A and B)*

50 queries with their expected slot interpretation, written **before any
tuning**. Coverage: all 12 access needs, every age range, weekday and
time-of-day phrasing, price, distance bands, crosswalk-only sports,
out-of-scope questions that must be refused, and unpublished-attribute
questions that must hand over. In the repository, run in CI.

### 6.4 D2 — Vocabularies served at runtime

The extractor needs the exact enum values at prompt time, read from the
database, not pasted into a prompt. A hardcoded list drifts the first time the
publisher adds a thirteenth access need, and the failure is silent. Follow the
pattern `/sports` and `/facility-types` already use.

### 6.5 D3 — Natural-language crosswalk

A reviewed mapping from how people speak to vocabulary values, in the shape of
`ds09_sport_vocabulary.yaml`: a decided relation and a written reason per row.
This is the auditable alternative to embeddings for *filters*, and it is why
Epic C's vector search is confined to descriptions rather than used for slot
resolution.

Seed rows: "kids" / "my son is 8" → Child (5-12) · "quiet" → Sensory friendly ·
"wheelchair" → Wheelchair accessible · "weekend" → saturday, sunday · "after
school" → after_school · "deaf" → Deaf or hearing impaired, consider Auslan.
Unreviewed phrasings surface in a gap report, as `sport_crosswalk_gap` does now.

### 6.6 D4 — Call-ahead question bank *(Epic B)*

Per attribute, and per sport where it matters, the question worth asking and its
order of consequence. Team-authored and source-cited per the project brief; the
schema and loading are infrastructure work, the content is not one person's job.

### 6.7 D5 — Chunk and embedding pipeline *(Epic C)* — **schema change**

The first structural change this iteration makes. A new migration adds:

```
CREATE EXTENSION vector;

program_description_chunk
  chunk_id            bigserial PK
  program_id          FK → program (ON DELETE CASCADE)
  chunk_index         integer          -- position within the description
  content             text             -- the chunk as embedded
  content_sha256      char(64)         -- skip re-embedding unchanged text
  embedding           vector(1024)
  embedding_model     text             -- e.g. amazon.titan-embed-text-v2:0
  source_id           text FK → source
  load_run_id         bigint FK → load_run
  embedded_at         timestamptz
  UNIQUE (program_id, chunk_index)
  HNSW index on embedding
```

Rules this table follows, consistent with the rest of the schema:

- **Provenance travels with the chunk.** `source_id` and `load_run_id` are
  carried, so a retrieved sentence is traceable to a publisher and a dated run
  exactly like every other fact in the product.
- **The model is recorded.** Changing embedding model invalidates the vectors;
  storing the model id makes that detectable rather than silent.
- **Re-embedding is content-addressed.** `content_sha256` means a weekly load
  with unchanged descriptions re-embeds nothing.
- **Chunks are derived, never authored.** They are rebuilt by the derive stage,
  which already runs inline in the loader.

Pipeline placement: chunk and embed in the **derive stage** after a DS-09 load
commits, alongside `venue_match` and `place_geography`. This is the same
`derive/run.py` sequence, extended by one step, and it is also where the
Bedrock endpoint is needed at ingest time.

### 6.8 D6 — Retrieval evaluation set *(Epic C)*

30 questions paired with the programme and sentence that should be retrieved.
Measures recall@k and citation correctness. Written before tuning the chunk size
or the relevance floor, for the same reason as D1.

### 6.9 D7 — Privacy-safe telemetry

Prompts are not logged (§9). Aggregate counters only: intent distribution,
refusal rate, zero-result rate, handover rate, retrieval-miss rate. Decide the
shape before building.

### 6.10 Two data-quality decisions to record

**`time_of_day` is not all times of day.** It contains `after_school`,
`all_day` and `school_holiday_program`. Does an after-school programme answer
"what is on in the afternoon"? A person decides, and the decision goes into D3.

**`Open to everyone` is not an access need.** It is the absence of a
restriction. Treated as a filter value, "find me wheelchair accessible
programmes" could exclude programmes open to everyone — which include
wheelchair users. This one can actively harm a result.

---

## 7. Evaluation

Run in CI, reported in the iteration report.

| Metric | Target | Method |
|---|---|---|
| Misparse rate (A, B) | **< 20%** | Slots vs labelled expectation, 50-query gold set |
| Unsupported claims (A, B) | **Zero** | Templated answers only; a generated sentence in these paths fails the build |
| Citation accuracy (C) | **100%** | Every claim traceable to the quoted chunk; unsupported answers discarded |
| Retrieval recall@3 (C) | **≥ 80%** | 30-question retrieval set |
| Refusal correctness | **100%** | No model call on the out-of-scope set |
| Rule violations R1–R4 | **Zero** | A test per rule |

---

## 8. Accessibility

WCAG 2.2 AA, and an assistant is the easiest place to lose it.

**8.1** Keyboard parity: everything voice does, the keyboard does.
**8.2** Results, interpretation changes, errors and refusals are announced in an
ARIA live region.
**8.3** Provenance in voice: spoken answers give the fact and name the provider,
and say that the quoted sentence and sources are on screen. Nothing is hidden —
this is a presentation difference, not a reduction.
**8.4** Microphone state is visible and announced.
**8.5** No time limits on speaking, no penalty for a pause.
**8.6** Reflow at 320 px, 24 px targets.

---

## 9. Privacy and security changes

The first feature where user-entered text leaves the device.

1. **Queries are transmitted** to Bedrock in ap-southeast-2; data stays in
   Australia. Say so in the interface, not only in a policy page.
2. **Prompts are not logged**, and not written to CloudWatch. Someone will type
   "gym near my son's school in Berwick". Telemetry is aggregate only.
3. **No audio leaves the device.**
4. **No conversation is persisted.**
5. **The corpus is publisher text, not user text.** Nothing a user types is ever
   embedded or stored in the vector table.
6. **Security plan** gains a risk row for the Bedrock dependency and the egress
   path; the privacy section is amended — "no personal information is stored"
   stays true, "nothing is transmitted" does not.
7. **A Bedrock spend alarm** on the existing budget guard.

---

## 10. Dependencies and risks

### 10.1 Blocked on the account holder — raise on day one

The deploy user cannot read or amend IAM (`iam:ListAttachedRolePolicies` is
denied), matching the existing note that the execution role is built by the
account holder. Two things are needed:

1. `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the
   assistant and derive roles, scoped to `anthropic.claude-haiku-4-5-*` and
   `amazon.titan-embed-text-v2*`.
2. **Bedrock model access enabled** for Anthropic and Amazon models in
   ap-southeast-2 — a separate per-account console opt-in. A model appearing in
   `list-foundation-models` does not mean the account may invoke it.

In Iteration 1 the OIDC trust policy blocked deployment twice, about a day each
time. Same dependency, known three weeks early.

### 10.2 Other risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Speech recognition fails on Victorian place names | High | Test day one; `/locations/resolve` trigram suggestions turn a miss into "did you mean…" |
| iOS Safari Web Speech support inconsistent | Medium | Feature-detect, fall back to text; Transcribe/Polly is the costed fallback |
| Epic C answers drift into advice the provider did not give | Medium | R4, plus AC-C1.5 confining retrieval to the programmes under discussion |
| Retrieval returns a plausible chunk from the wrong provider | Medium | AC-C1.5; citation shows provider name, so a wrong one is visible |
| Scope creep into open-ended chat | Medium | Three epics, refusal path, §2.5 recorded |
| Endpoint misconfiguration hangs instead of failing | Medium | §3.4 items 2 and 3; add a startup reachability check |
| Six people on one codebase | Medium | Epics A, B and C touch different layers; D-items are independently ownable |

---

## 11. Sequencing

Three weeks, six people. The epics are parallelisable because they touch
different layers: A is intent and the API, B is reference data and presentation,
C is the pipeline and the database.

| Week | Work | Cut line |
|---|---|---|
| 1 | IAM request day one · D1 gold set · D2 vocabulary endpoint · intent and slot layer · endpoint provisioned · `pgvector` migration and D5 chunking · speech spike on place names | — |
| 2 | Epic A event intents · D3 crosswalk · D4 question bank · Epic B handover · Epic C retrieval and R4 validation · D6 retrieval set · evaluation in CI | If slipping: Epic C degrades to showing the retrieved sentence with no paraphrase — still useful, no generation |
| 3 | Voice adapter across all three epics · accessibility pass · measurement run · walkthrough recording | Voice is the designed cut; the chatbot ships without it |

Epic C has a graceful degradation the others do not: **retrieval without
generation** — quote the matching sentence and skip the paraphrase. That keeps
the vector work visible and removes R4's risk entirely if time runs short.

---

## 12. Open questions for the team

1. Does the team accept deferring the council coverage view (§2.4)?
2. Who authors the call-ahead question bank content (D4)?
3. Does an after-school programme answer "what is on in the afternoon" (§6.10)?
4. Is the assistant reachable from venue and event pages, or a dedicated entry
   point only?
5. **ADR-006 is Proposed and unratified** and conflicts with task D5. Rule R2
   depends on it; settle it this iteration.
6. Should the venue free-text corpus (§6.2) be measured and added to Epic C, or
   left out of this iteration?
