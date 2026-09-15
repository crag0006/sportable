-- ============================================================================
-- 010_program_venue_geography.sql
--
-- Iteration 2, Epic 4, D4. Derives a suburb and a postcode for every DS-09
-- place from the coordinates the publisher already gives us, so that a place
-- the publisher did not bother to file under a suburb is still findable.
--
-- THE GAP THIS CLOSES, IN NUMBERS
--     AAA Play publishes 552 places. All 552 carry a geocode
--     (acf.facility_location.lat/lng), but only 288 of them — 52.2% — carry a
--     parsed post_code / city / state_short as well. The other 264 have a
--     free-text address and a point, and nothing else.
--
--     009 stores what the publisher published: program_venue.suburb_name and
--     program_venue.postcode are NULL for those 264. Every query that pairs a
--     suburb with a postcode therefore drops them — the places dropdown in
--     backend/app/repositories/postgres.py does exactly that with
--     `WHERE suburb_name IS NOT NULL AND postcode IS NOT NULL`. AC4.1.1 makes
--     Suburb/Postcode a REQUIRED search field, so those 264 places are not
--     merely missing a label: they are unreachable. That is a correctness
--     defect, not a presentation one.
--
-- WHY POINT-IN-POLYGON AND NOT ADDRESS PARSING
--     The address strings are provider-typed prose ("Cnr Blah St & Blah Rd,
--     opposite the oval"). Parsing them would manufacture a suburb out of a
--     string that never contained one, which is the one thing this project
--     never does. A coordinate inside an ABS Suburbs and Localities polygon is
--     a fact with a published boundary behind it; a regular expression over
--     somebody's prose is a guess wearing a fact's clothes.
--
--     DS-07 (Suburbs and Localities) and DS-08 (Postal Areas) are already
--     loaded as `suburb` and `postal_area`, both geometry(MultiPolygon, 7844),
--     the same CRS as program_venue.geom. No transform is involved.
--
-- WHAT IS DELIBERATELY NOT DONE HERE
--     Nothing overwrites a publisher value. suburb_name, postcode and
--     full_address keep exactly what DS-09 published, because full_address is
--     what a HUMAN reads on the card and the publisher's own words are what we
--     attribute to them. The derived columns are what the QUERY matches on.
--     Where both exist they are compared, never merged — see the
--     program_venue_geography_check view at the foot of this file.
--
--     A point that falls inside no polygon derives NULL. That is the correct
--     answer and not a failure to be patched with a nearest-polygon fallback:
--     "the nearest suburb to this point" is not the same statement as "this
--     point is in this suburb", and only the second one is true enough to put
--     in a search index.
--
-- REVERSIBILITY
--     Additive only. Three new columns on program_venue, one view, one
--     materialised view. No existing column, constraint, index or view is
--     altered or dropped, so the rollback at the foot of this file is the whole
--     of it.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Derived columns on program_venue
-- ---------------------------------------------------------------------------

ALTER TABLE public.program_venue
    ADD COLUMN derived_suburb_code text,
    ADD COLUMN derived_suburb_name text,
    ADD COLUMN derived_postcode    text,
    ADD COLUMN derived_at          timestamp with time zone;

-- The gazetteer codes are foreign keys, not free text. This is the constraint
-- that stops somebody "helpfully" copying the publisher's suburb string into
-- derived_suburb_name during a future load: a value that is not an ABS code
-- cannot get in, so a derived column can only ever hold something a boundary
-- layer actually said.
--
-- Both layers are loaded with ON CONFLICT DO UPDATE and never deleted (see
-- ingestion/loaders/loader.py), so a boundary refresh cannot orphan these rows.
ALTER TABLE ONLY public.program_venue
    ADD CONSTRAINT program_venue_derived_suburb_fkey
        FOREIGN KEY (derived_suburb_code) REFERENCES public.suburb(suburb_code);

ALTER TABLE ONLY public.program_venue
    ADD CONSTRAINT program_venue_derived_postcode_fkey
        FOREIGN KEY (derived_postcode) REFERENCES public.postal_area(poa_code);

-- A name without its code would be a label nobody can trace back to a polygon.
ALTER TABLE public.program_venue
    ADD CONSTRAINT program_venue_derived_suburb_complete
        CHECK ((derived_suburb_code IS NULL) = (derived_suburb_name IS NULL));

-- The three-state rule that makes "no polygon contains this point" readable.
-- derived_at NULL means the point-in-polygon has not been run for this row;
-- derived_at set with both values NULL means it was run and found nothing.
-- Without this, an absence and an omission look identical, and a reader of
-- this table would have to guess which one they are looking at.
ALTER TABLE public.program_venue
    ADD CONSTRAINT program_venue_derived_needs_a_run
        CHECK (
            derived_at IS NOT NULL
            OR (derived_suburb_code IS NULL AND derived_postcode IS NULL)
        );

COMMENT ON COLUMN public.program_venue.derived_suburb_code IS
    'ASGS Suburbs and Localities code (DS-07) of the polygon containing this places geocode, or NULL where no polygon contains it. Derived, never published: the publishers own suburb stays in suburb_name and the two are compared rather than merged.';

COMMENT ON COLUMN public.program_venue.derived_suburb_name IS
    'The ABS name for derived_suburb_code, carried alongside the code so a reader does not have to join to see it. ABS names carry a disambiguating suffix on duplicated localities, for example "Preston (Vic.)"; strip it with the same expression the API uses before showing or matching a typed name.';

COMMENT ON COLUMN public.program_venue.derived_postcode IS
    'ASGS Postal Area code (DS-08) of the polygon containing this places geocode, or NULL where no polygon contains it. Postal areas approximate Australia Post postcodes and are not authoritative for delivery; this column exists so a place can be FOUND by postcode, never to print a postal address.';

COMMENT ON COLUMN public.program_venue.derived_at IS
    'When the point-in-polygon last ran for this row. NULL means it has never run (including every row with no geocode, which has nothing to run against). Set with both derived values NULL means it ran and the point fell in no polygon, which is a recorded absence and the correct answer, not a defect to patch with a nearest-polygon guess.';


-- ---------------------------------------------------------------------------
-- 2. Initial backfill
--
-- The ongoing job belongs to derive/place_geography.py, which runs this same
-- statement after every DS-09 load and is re-runnable. It is repeated here so
-- that the migration leaves the database in a usable state rather than in one
-- where every derived column is NULL until somebody remembers to run a script.
--
-- ST_Contains and not ST_DWithin: containment is the whole claim being made.
-- A point exactly on a shared boundary is contained by neither polygon and
-- derives NULL — measure-zero for a geocode, and an honest NULL beats an
-- arbitrary tie-break.
--
-- The LATERAL ... LIMIT 1 exists only to make the statement total: ASGS
-- polygons do not overlap, so at most one row can match, and ORDER BY the code
-- makes the impossible case deterministic instead of arbitrary.
-- ---------------------------------------------------------------------------

UPDATE public.program_venue pv
   SET derived_suburb_code = g.suburb_code,
       derived_suburb_name = g.suburb_name,
       derived_postcode    = g.poa_code,
       derived_at          = now()
  FROM (
        SELECT p.program_venue_id,
               sb.suburb_code,
               sb.suburb_name,
               pa.poa_code
          FROM public.program_venue p
          LEFT JOIN LATERAL (
                SELECT s.suburb_code, s.suburb_name
                  FROM public.suburb s
                 WHERE public.ST_Contains(s.geom, p.geom)
                 ORDER BY s.suburb_code
                 LIMIT 1
          ) sb ON true
          LEFT JOIN LATERAL (
                SELECT a.poa_code
                  FROM public.postal_area a
                 WHERE public.ST_Contains(a.geom, p.geom)
                 ORDER BY a.poa_code
                 LIMIT 1
          ) pa ON true
         WHERE p.geom IS NOT NULL
  ) g
 WHERE pv.program_venue_id = g.program_venue_id;

-- No index is added on the derived columns, deliberately. program_venue holds
-- 552 rows; every query below reads all of them and a planner given an index
-- here would ignore it. An index added "for consistency" on a table this size
-- is cost with no benefit, and it would have to be maintained on every load.


-- ---------------------------------------------------------------------------
-- 3. Agreement cross-check
--
-- For the 288 places that carry BOTH a published and a derived value, the two
-- are statements about the same place from two independent directions: what the
-- provider typed, and where the provider's own geocode actually falls. When
-- they disagree, one of the two is wrong — either the address was typed for a
-- different place or the geocode landed somewhere it should not have — and
-- which one it is cannot be decided from here.
--
-- So this view decides nothing. It puts the two values side by side, row by
-- row, and lets the quality report count them and name the offenders.
-- derive/place_geography.py aggregates over exactly this view, so the
-- normalisation rule below is defined once and cannot drift between the report
-- and the data behind it.
--
-- Not materialised: it is read by a report, never by a request.
-- ---------------------------------------------------------------------------

CREATE VIEW public.program_venue_geography_check AS
SELECT
    pv.program_venue_id,
    pv.name,
    pv.full_address,
    pv.suburb_name      AS published_suburb,
    pv.derived_suburb_name,
    pv.postcode         AS published_postcode,
    pv.derived_postcode,
    pv.derived_at,

    -- NULL, not false, where either side is silent. An absent publisher value
    -- is not a disagreement with anything; counting it as one would turn a
    -- known gap into a fabricated conflict and drag the agreement rate down
    -- with rows that never made a claim.
    CASE
        WHEN pv.suburb_name IS NULL OR pv.derived_suburb_name IS NULL THEN NULL
        ELSE lower(btrim(regexp_replace(pv.suburb_name, '\s*\([^)]*\)$', '')))
           = lower(btrim(regexp_replace(pv.derived_suburb_name, '\s*\([^)]*\)$', '')))
    END AS suburb_agrees,

    CASE
        WHEN pv.postcode IS NULL OR pv.derived_postcode IS NULL THEN NULL
        ELSE btrim(pv.postcode) = btrim(pv.derived_postcode)
    END AS postcode_agrees

FROM public.program_venue pv;

COMMENT ON VIEW public.program_venue_geography_check IS
    'Published against derived suburb and postcode, one row per DS-09 place, for the data quality report. A false in either agreement column is a real conflict between the publishers address and the publishers geocode and is worth a human look; a NULL means one side said nothing and there is nothing to compare.';

COMMENT ON COLUMN public.program_venue_geography_check.suburb_agrees IS
    'Compared on the normalised name: lowercased, trimmed, and with the ABS disambiguating suffix removed so that "Preston" and "Preston (Vic.)" agree. NULL where either side is absent.';


-- ---------------------------------------------------------------------------
-- 4. place_vocabulary — the search-facing suburb/postcode list
--
-- WHAT THE DROPDOWN DOES TODAY AND WHY IT IS WRONG
--     SQL_PLACES in backend/app/repositories/postgres.py builds the required
--     Suburb/Postcode field from `venue`, grouping the publisher's own suburb
--     and postcode strings and discarding any row where either is NULL. That
--     has two faults: it drops every place the publisher did not file, and the
--     labels it does produce are publisher strings that the resolver may not
--     recognise — resolve_location matches a typed name against
--     `search_location`, which is the ABS gazetteer. A label the dropdown
--     offers but the resolver cannot resolve is worse than no label at all.
--
-- WHAT THIS VIEW DOES INSTEAD
--     Every row here is keyed on a polygon: the suburb comes from DS-07 and
--     the postcode from DS-08, for venues and DS-09 places alike. That is the
--     same vocabulary `search_location` is built from, so anything this view
--     offers is by construction resolvable, and a suburb that works on the map
--     page cannot fail on the events page. The column names — suburb,
--     postcode, venue_count — are the ones SQL_PLACES already returns, so the
--     API change is the FROM clause and nothing else.
--
--     Venues are located inline here rather than through stored columns of
--     their own. DS-01 is not the dataset with the gap D4 is about, and adding
--     a second set of derived columns nobody reads would be inventory rather
--     than value; the refresh is offline and a GiST-indexed containment test
--     over the venue table costs seconds.
--
--     A pair needs both halves, so a place whose point lands in a suburb but in
--     no postal area contributes to neither pair — the dropdown's contract IS
--     the pair. That gap is not swallowed: place_geography.py counts and prints
--     it, so a hole in the postal layer shows up as a number rather than as
--     quietly missing rows.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW public.place_vocabulary AS
WITH located AS (
    SELECT 'venue'::text AS thing,
           sb.suburb_code,
           sb.suburb_name,
           pa.poa_code
      FROM public.venue v
      LEFT JOIN LATERAL (
            SELECT s.suburb_code, s.suburb_name
              FROM public.suburb s
             WHERE public.ST_Contains(s.geom, v.geom)
             ORDER BY s.suburb_code
             LIMIT 1
      ) sb ON true
      LEFT JOIN LATERAL (
            SELECT a.poa_code
              FROM public.postal_area a
             WHERE public.ST_Contains(a.geom, v.geom)
             ORDER BY a.poa_code
             LIMIT 1
      ) pa ON true

    UNION ALL

    -- The DS-09 side reads the stored columns: the work was done once at load
    -- time and repeating it here would let the two answers drift apart.
    SELECT 'program_venue'::text AS thing,
           pv.derived_suburb_code,
           pv.derived_suburb_name,
           pv.derived_postcode
      FROM public.program_venue pv
)
SELECT
    -- The plain label, because the API strips the ABS suffix before matching a
    -- typed name (PLAIN_LABEL in postgres.py) and a dropdown entry that does
    -- not survive that strip would not resolve.
    regexp_replace(located.suburb_name, '\s*\([^)]*\)$', '')        AS suburb,
    located.poa_code                                                AS postcode,
    array_agg(DISTINCT located.suburb_code)                         AS suburb_codes,
    (count(*) FILTER (WHERE located.thing = 'venue'))::integer         AS venue_count,
    (count(*) FILTER (WHERE located.thing = 'program_venue'))::integer AS program_venue_count,
    (count(*))::integer                                                AS place_count
FROM located
WHERE located.suburb_code IS NOT NULL
  AND located.poa_code IS NOT NULL
GROUP BY 1, 2;

-- REFRESH MATERIALIZED VIEW CONCURRENTLY needs a unique index over plain
-- column names, which is why suburb is a column of the view and not an
-- expression applied on the way out.
CREATE UNIQUE INDEX place_vocabulary_pk_idx
    ON public.place_vocabulary (suburb, postcode);
CREATE INDEX place_vocabulary_postcode_idx
    ON public.place_vocabulary (postcode);
CREATE INDEX place_vocabulary_suburb_trgm_idx
    ON public.place_vocabulary USING gin (lower(suburb) public.gin_trgm_ops);

COMMENT ON MATERIALIZED VIEW public.place_vocabulary IS
    'Suburb and postcode pairs that actually contain something, with how many venues and how many DS-09 places fall in each. Backs the required Suburb/Postcode field in AC4.1.1. Every pair is decided by point-in-polygon against DS-07 and DS-08, the same layers search_location is built from, so every label offered here resolves. Refreshed by derive/place_geography.py; add it to status_builder.READ_MODEL_VIEWS when the DS-09 derive stage joins the pipeline run.';

COMMENT ON COLUMN public.place_vocabulary.suburb_codes IS
    'Every ASGS locality code that contributed to this pair. Usually one. More than one means two same-named localities share a postal area, which the label alone cannot tell apart — the codes are kept so a caller that needs to can.';

COMMENT ON COLUMN public.place_vocabulary.venue_count IS
    'DS-01 venues whose point falls in this suburb and this postal area. Named venue_count because that is what the places endpoint already returns; it counts position, not the publishers suburb string.';

COMMIT;


-- ============================================================================
-- ROLLBACK
--
--   BEGIN;
--   DROP MATERIALIZED VIEW IF EXISTS public.place_vocabulary;
--   DROP VIEW IF EXISTS public.program_venue_geography_check;
--   ALTER TABLE public.program_venue
--       DROP CONSTRAINT IF EXISTS program_venue_derived_needs_a_run,
--       DROP CONSTRAINT IF EXISTS program_venue_derived_suburb_complete,
--       DROP CONSTRAINT IF EXISTS program_venue_derived_postcode_fkey,
--       DROP CONSTRAINT IF EXISTS program_venue_derived_suburb_fkey;
--   ALTER TABLE public.program_venue
--       DROP COLUMN IF EXISTS derived_at,
--       DROP COLUMN IF EXISTS derived_postcode,
--       DROP COLUMN IF EXISTS derived_suburb_name,
--       DROP COLUMN IF EXISTS derived_suburb_code;
--   COMMIT;
--
--   The view must go before the columns: it reads them, and PostgreSQL will
--   refuse the DROP COLUMN rather than cascade into it.
-- ============================================================================
