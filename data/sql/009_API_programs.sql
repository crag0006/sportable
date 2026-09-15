-- ============================================================================
-- 009_iteration2_programs.sql
--
-- Iteration 2, Epic 4. Adds the tables the events feature reads from.
--
-- WHY "program" AND NOT "event"
--     DS-09 publishes recurring programs: a weekday, a time of day, and no
--     dates at all. Naming the table `event` would invite the first person who
--     opens it to add a date column and then fill it by parsing prose out of a
--     description, and several DS-09 descriptions do contain text like
--     "Term dates: 16 July - 17 September". A wrong date in front of somebody
--     deciding whether to travel is the most expensive error this product can
--     make. The table is called what the rows are; /events with kind: "program"
--     is the API's presentation of it and lives in the API layer.
--
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
--     It adds nothing to venue, venue_amenity_status or venue_access_chain, and
--     it introduces no publication_status column anywhere. DS-09 is not
--     government published, and the register's standing position is that
--     government records are the only thing that can produce a confirmed. These
--     tables sit beside the access chain and never feed it.
--
-- REVERSIBILITY
--     Additive only. No existing table, column, type or index is altered, so a
--     rollback is the DROP block at the foot of this file and nothing else.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Types
-- ---------------------------------------------------------------------------

-- 'program'  a recurring activity with a weekday and no dates. Every DS-09 row.
-- 'fixture'  a dated occurrence. Nothing writes this yet. It exists so the
--            enum does not have to change when a dated source arrives, and so
--            the CHECK below can express the date rule for both kinds today.
CREATE TYPE public.program_kind AS ENUM (
    'program',
    'fixture'
);

COMMENT ON TYPE public.program_kind IS
    'Whether a row recurs on a weekday with no dates, or occurs once at a stated time. The API exposes this as the kind field on /events.';


-- ---------------------------------------------------------------------------
-- program_organisation
-- ---------------------------------------------------------------------------

CREATE TABLE public.program_organisation (
    organisation_id text NOT NULL,
    source_id       text NOT NULL,
    load_run_id     bigint NOT NULL,
    publisher_key   integer NOT NULL,
    name            text NOT NULL,
    website_url     text,
    source_url      text,
    publisher_last_updated timestamp with time zone,
    retrieved_at    timestamp with time zone NOT NULL,
    CONSTRAINT program_organisation_pkey PRIMARY KEY (organisation_id)
);

COMMENT ON TABLE public.program_organisation IS
    'Providers who run the programs, from the DS-09 organisation post type. Organisation-level contact only; no individual is stored.';


-- ---------------------------------------------------------------------------
-- program_venue
-- ---------------------------------------------------------------------------

CREATE TABLE public.program_venue (
    program_venue_id text NOT NULL,
    source_id        text NOT NULL,
    load_run_id      bigint NOT NULL,
    publisher_key    integer NOT NULL,
    name             text NOT NULL,
    full_address     text,
    suburb_name      text,
    postcode         text,
    publisher_lga_label text,
    geom             public.geometry(Point,7844),
    publisher_place_ref text,
    accessible_car_spaces integer,
    website_url      text,
    source_url       text,
    publisher_last_updated timestamp with time zone,
    retrieved_at     timestamp with time zone NOT NULL,
    venue_id         text,
    match_distance_m numeric,
    match_name_similarity numeric,
    venue_matched    boolean GENERATED ALWAYS AS (venue_id IS NOT NULL) STORED,
    CONSTRAINT program_venue_pkey PRIMARY KEY (program_venue_id),
    CONSTRAINT program_venue_geom_is_point
        CHECK ((geom IS NULL) OR (public.st_geometrytype(geom) = 'ST_Point'::text)),
    CONSTRAINT program_venue_match_evidence
        CHECK ((venue_id IS NULL) OR (match_distance_m IS NOT NULL AND match_name_similarity IS NOT NULL)),
    CONSTRAINT program_venue_car_spaces_non_negative
        CHECK ((accessible_car_spaces IS NULL) OR (accessible_car_spaces >= 0))
);

COMMENT ON TABLE public.program_venue IS
    'Places where DS-09 programs run. A separate table from venue on purpose: these are the publishers own records, not government venue records, and they must never be mistaken for one another in a join.';

COMMENT ON COLUMN public.program_venue.venue_id IS
    'The matched government venue, or NULL. NULL is the normal case and not a defect: it means this place is not in the DS-01 register, which is true of church halls, private gyms and community centres. The program still displays, with the publishers own detail.';

COMMENT ON COLUMN public.program_venue.venue_matched IS
    'Generated from venue_id so the flag cannot drift out of step with the key it describes. Do not write to this column.';

COMMENT ON COLUMN public.program_venue.match_distance_m IS
    'Straight-line metres to the matched venue. Stored as evidence: a match at 140 m is a weaker claim than one at 4 m, and the venue page should be able to say which it had.';

COMMENT ON COLUMN public.program_venue.match_name_similarity IS
    'pg_trgm similarity between the two names at match time. Distance alone produced false neighbours in testing, including a cafe 5 m from a gym, so both pieces of evidence are recorded rather than just the verdict.';

COMMENT ON COLUMN public.program_venue.publisher_place_ref IS
    'The publishers own place identifier, retained so the point can be re-derived from the address if the geocode provenance question closes against persisting it. See the DS-09 open questions. Not used for matching.';

COMMENT ON COLUMN public.program_venue.accessible_car_spaces IS
    'Count of accessible car spaces as published. Unlike the boolean attributes this field has a real null state: providers leave it blank or type a literal 0, and those are different statements, so 0 is stored as a recorded zero and blank as NULL.';


-- ---------------------------------------------------------------------------
-- program_venue_attribute
-- ---------------------------------------------------------------------------

CREATE TABLE public.program_venue_attribute (
    program_venue_id text NOT NULL,
    attribute_key    text NOT NULL,
    attribute_label  text NOT NULL,
    source_id        text NOT NULL,
    load_run_id      bigint NOT NULL,
    CONSTRAINT program_venue_attribute_pkey PRIMARY KEY (program_venue_id, attribute_key)
);

COMMENT ON TABLE public.program_venue_attribute IS
    'Accessibility attributes the publisher ticked for a place. THERE IS DELIBERATELY NO BOOLEAN COLUMN HERE. The source booleans have no null state, so a false is an unticked form field and not a recorded absence; a row exists only where the publisher said yes, and the absence of a row means no published information. Adding an is_available column would recreate exactly the ambiguity this shape removes. The publishers changing_places flag is not loaded at all: it reports 275 of 552 places against 163 accredited statewide in DS-02, and Changing Places is a trade marked accreditation.';

COMMENT ON COLUMN public.program_venue_attribute.attribute_label IS
    'Display wording for the attribute. These are provider claims shown under the publishers own attribution, never a facility status and never an input to the access chain.';


-- ---------------------------------------------------------------------------
-- program
-- ---------------------------------------------------------------------------

CREATE TABLE public.program (
    program_id       text NOT NULL,
    source_id        text NOT NULL,
    load_run_id      bigint NOT NULL,
    publisher_key    integer NOT NULL,
    kind             public.program_kind DEFAULT 'program'::public.program_kind NOT NULL,
    name             text NOT NULL,
    description      text,
    starts_at        timestamp with time zone,
    ends_at          timestamp with time zone,
    recurrence_weekdays text[] DEFAULT '{}'::text[] NOT NULL,
    recurrence_time_of_day text[] DEFAULT '{}'::text[] NOT NULL,
    is_free          boolean,
    price_label      text,
    age_ranges       text[] DEFAULT '{}'::text[] NOT NULL,
    welcoming        text[] DEFAULT '{}'::text[] NOT NULL,
    environment      text[] DEFAULT '{}'::text[] NOT NULL,
    program_venue_id text,
    organisation_id  text,
    geom             public.geometry(Point,7844) NOT NULL,
    publisher_lga_label text,
    publisher_region_label text,
    registration_url text,
    source_url       text,
    publisher_last_updated timestamp with time zone,
    retrieved_at     timestamp with time zone NOT NULL,
    CONSTRAINT program_pkey PRIMARY KEY (program_id),
    CONSTRAINT program_geom_is_point
        CHECK ((public.st_geometrytype(geom) = 'ST_Point'::text)),
    CONSTRAINT program_dates_match_kind CHECK (
        ((kind = 'program'::public.program_kind) AND starts_at IS NULL AND ends_at IS NULL)
        OR
        ((kind = 'fixture'::public.program_kind) AND starts_at IS NOT NULL)
    ),
    CONSTRAINT program_weekdays_are_valid CHECK (
        recurrence_weekdays <@ ARRAY[
            'monday','tuesday','wednesday','thursday','friday','saturday','sunday'
        ]::text[]
    )
);

COMMENT ON TABLE public.program IS
    'Accessible sport and recreation programs. Every DS-09 row is an accessible programme: that is the entire purpose of the publisher, and nothing in this table needs filtering to make it so.';

COMMENT ON COLUMN public.program.starts_at IS
    'NULL for every row of kind program, and the CHECK constraint enforces it. DS-09 publishes no dates. Some descriptions contain date text such as term dates; that text is prose and is never parsed into this column. A wrong date here sends somebody on a trip that was not happening.';

COMMENT ON COLUMN public.program.recurrence_weekdays IS
    'Lowercase English weekday names, Monday first. May legitimately be empty: the publisher allows a programme with no weekday recorded, and an empty array means not published rather than never.';

COMMENT ON COLUMN public.program.is_free IS
    'From the publishers price field. NULL where the publisher recorded no price at all, which is not the same as free.';

COMMENT ON COLUMN public.program.geom IS
    'The programmes point, preferring the linked places geocode and falling back to the programmes own coordinates. Rows with neither are quarantined as COORD_MISSING and never reach this table.';

COMMENT ON COLUMN public.program.publisher_lga_label IS
    'The council name as the publisher labelled it. A cross-check only. Scope and the council shown to a user are decided by point-in-polygon against DS-06, because the publishers taxonomy carries junk terms and one term naming two councils.';

COMMENT ON COLUMN public.program.description IS
    'Provider prose, HTML stripped, shown as recorded with attribution. Never parsed for access claims. Several listings describe parking or bathrooms in this field; that is the providers word, not a published facility status.';


-- ---------------------------------------------------------------------------
-- program_access_need
-- ---------------------------------------------------------------------------

CREATE TABLE public.program_access_need (
    program_id       text NOT NULL,
    access_need_key  text NOT NULL,
    access_need_label text NOT NULL,
    source_id        text NOT NULL,
    load_run_id      bigint NOT NULL,
    CONSTRAINT program_access_need_pkey PRIMARY KEY (program_id, access_need_key)
);

COMMENT ON TABLE public.program_access_need IS
    'Which access needs a programme states it caters for. THIS IS A REFINEMENT FILTER, NEVER THE PREDICATE THAT BUILDS THE EVENTS LIST. About half of all programmes carry no tag, including the publishers own wheelchair basketball programme, so filtering the list on a tag would hide the majority of accessible programmes rather than narrowing to them. No rows means the provider did not say, not that the programme excludes anyone.';


-- ---------------------------------------------------------------------------
-- program_sport
-- ---------------------------------------------------------------------------

CREATE TABLE public.program_sport (
    program_id  text NOT NULL,
    sport_key   text NOT NULL,
    sport_label text NOT NULL,
    source_id   text NOT NULL,
    load_run_id bigint NOT NULL,
    CONSTRAINT program_sport_pkey PRIMARY KEY (program_id, sport_key)
);

COMMENT ON TABLE public.program_sport IS
    'Sports a programme covers, from the publishers activity_type taxonomy. Some terms are not sports, for example Art and Playground, and are kept as published rather than filtered, so the vocabulary join to venue_sport is a left join and a miss is not an error.';


-- ---------------------------------------------------------------------------
-- Foreign keys
-- ---------------------------------------------------------------------------

ALTER TABLE ONLY public.program_organisation
    ADD CONSTRAINT program_organisation_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);
ALTER TABLE ONLY public.program_organisation
    ADD CONSTRAINT program_organisation_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);

ALTER TABLE ONLY public.program_venue
    ADD CONSTRAINT program_venue_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);
ALTER TABLE ONLY public.program_venue
    ADD CONSTRAINT program_venue_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);
ALTER TABLE ONLY public.program_venue
    ADD CONSTRAINT program_venue_venue_id_fkey FOREIGN KEY (venue_id) REFERENCES public.venue(venue_id) ON DELETE SET NULL;

ALTER TABLE ONLY public.program_venue_attribute
    ADD CONSTRAINT program_venue_attribute_venue_fkey FOREIGN KEY (program_venue_id) REFERENCES public.program_venue(program_venue_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.program_venue_attribute
    ADD CONSTRAINT program_venue_attribute_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);
ALTER TABLE ONLY public.program_venue_attribute
    ADD CONSTRAINT program_venue_attribute_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);

ALTER TABLE ONLY public.program
    ADD CONSTRAINT program_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);
ALTER TABLE ONLY public.program
    ADD CONSTRAINT program_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);
ALTER TABLE ONLY public.program
    ADD CONSTRAINT program_venue_fkey FOREIGN KEY (program_venue_id) REFERENCES public.program_venue(program_venue_id) ON DELETE SET NULL;
ALTER TABLE ONLY public.program
    ADD CONSTRAINT program_organisation_fkey FOREIGN KEY (organisation_id) REFERENCES public.program_organisation(organisation_id) ON DELETE SET NULL;

ALTER TABLE ONLY public.program_access_need
    ADD CONSTRAINT program_access_need_program_fkey FOREIGN KEY (program_id) REFERENCES public.program(program_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.program_access_need
    ADD CONSTRAINT program_access_need_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);
ALTER TABLE ONLY public.program_access_need
    ADD CONSTRAINT program_access_need_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);

ALTER TABLE ONLY public.program_sport
    ADD CONSTRAINT program_sport_program_fkey FOREIGN KEY (program_id) REFERENCES public.program(program_id) ON DELETE CASCADE;
ALTER TABLE ONLY public.program_sport
    ADD CONSTRAINT program_sport_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);
ALTER TABLE ONLY public.program_sport
    ADD CONSTRAINT program_sport_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);


-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX program_geom_idx ON public.program USING gist (geom);
CREATE INDEX program_kind_idx ON public.program USING btree (kind);
CREATE INDEX program_venue_ref_idx ON public.program USING btree (program_venue_id);
CREATE INDEX program_organisation_ref_idx ON public.program USING btree (organisation_id);
CREATE INDEX program_weekday_idx ON public.program USING gin (recurrence_weekdays);
CREATE INDEX program_time_of_day_idx ON public.program USING gin (recurrence_time_of_day);
CREATE INDEX program_age_range_idx ON public.program USING gin (age_ranges);
CREATE INDEX program_free_idx ON public.program USING btree (is_free) WHERE is_free;
CREATE INDEX program_name_idx ON public.program USING gin (to_tsvector('english'::regconfig, name));

CREATE INDEX program_venue_geom_idx ON public.program_venue USING gist (geom);
CREATE INDEX program_venue_venue_id_idx ON public.program_venue USING btree (venue_id) WHERE venue_id IS NOT NULL;
CREATE INDEX program_venue_postcode_idx ON public.program_venue USING btree (postcode);

-- The matcher compares names with pg_trgm at 0.3, so it needs this to avoid a
-- sequential scan across every candidate pair.
CREATE INDEX program_venue_name_trgm_idx ON public.program_venue USING gin (lower(name) public.gin_trgm_ops);

CREATE INDEX program_access_need_key_idx ON public.program_access_need USING btree (access_need_key);
CREATE INDEX program_sport_key_idx ON public.program_sport USING btree (sport_key);

COMMIT;


-- ============================================================================
-- ROLLBACK
--
--   BEGIN;
--   DROP TABLE IF EXISTS public.program_sport;
--   DROP TABLE IF EXISTS public.program_access_need;
--   DROP TABLE IF EXISTS public.program_venue_attribute;
--   DROP TABLE IF EXISTS public.program;
--   DROP TABLE IF EXISTS public.program_venue;
--   DROP TABLE IF EXISTS public.program_organisation;
--   DROP TYPE  IF EXISTS public.program_kind;
--   COMMIT;
-- ============================================================================
