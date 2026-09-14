-- sql/008_events.sql
--
-- The events epic (Iteration 2, API contract v0.2 section 7).
--
-- ONE TABLE, TWO KINDS OF ROW
--
-- A "fixture" is a game with a start instant: PlayHQ (DS-10, when credentials
-- arrive) or any other dated source. A "program" is a recurring activity with
-- a weekday and a time of day but no date: AAA Play (DS-09). They share a
-- table because the events page lists both with the same venue access tiles
-- beside them, and the API says which rule applied (a date-range filter
-- selects fixtures by instant and programs by weekday).
--
-- WHAT THIS TABLE NEVER DOES
--
-- Nothing here writes a facility status. The four tiles beside an event are
-- read at request time from venue_amenity_status through event.venue_id, so
-- an event shows exactly what the venue page shows (AC4.2.2 / AC5.2.1). An
-- event whose venue could not be matched keeps its own name and point and
-- shows "no published information" for all four (AC4.2.3 / AC5.2.2). No
-- attribute of a publisher's venue record (AAA Play's booleans, PlayHQ's
-- address) is ever promoted into venue or venue_amenity_status; that is the
-- register's rule that only government records produce a confirmed.
--
-- VENUE MATCHING
--
-- venue_id is filled by derive/venue_match.py after load: the nearest DS-01
-- venue within 150 m whose name is similar (pg_trgm > 0.3), or an exact
-- point within 25 m, or a strong name match within 400 m. Everything else is
-- 'none' and the event is still listed. The basis and distance are kept so
-- the match can be audited and the threshold revisited without a reload.
--
-- PERSONAL DATA
--
-- No contact person, email or phone is stored. Publishers' registration URLs
-- and organisation names are the only contact routes (DS-09 card).

BEGIN;

CREATE TYPE event_kind AS ENUM ('fixture', 'program');

CREATE TABLE event (
    event_id                text PRIMARY KEY,
    source_id               text NOT NULL REFERENCES source(source_id),
    load_run_id             bigint NOT NULL REFERENCES load_run(load_run_id),
    kind                    event_kind NOT NULL,

    -- What is on
    title                   text NOT NULL,
    sport                   text,          -- a sport_vocabulary name where one maps
    sport_raw               text,          -- the publisher's own term, always kept
    competition             text,
    season                  text,
    grade                   text,
    round                   text,
    home_team               text,
    away_team               text,
    description             text,          -- publisher prose, displayed as such
    organisation            text,
    status                  text NOT NULL, -- fixtures: UPCOMING PENDING FINAL CANCELLED ABANDONED; programs: ACTIVE

    -- When: fixtures carry an instant, programs a weekly pattern
    starts_at               timestamptz,
    ends_at                 timestamptz,
    timezone                text NOT NULL DEFAULT 'Australia/Melbourne',
    weekdays                text[],        -- 'monday' .. 'sunday'; NULL or empty = not stated
    time_of_day             text[],        -- morning afternoon evening after_school all_day school_holiday_program
    price                   text,          -- 'free' | 'paid' | NULL = not stated
    age_ranges              text[],
    access_needs            text[],        -- publisher tags; empty = no published information, never a no

    -- Where, as published
    external_url            text NOT NULL, -- the publisher's own page; also the attribution link
    registration_url        text,
    venue_external_id       text,
    venue_name              text,
    venue_address           text,
    venue_suburb            text,
    venue_postcode          text,
    venue_geom              geometry(Point, 7844),

    -- Where, as matched by us
    venue_id                text REFERENCES venue(venue_id),
    venue_match_basis       text NOT NULL DEFAULT 'none',
    venue_match_distance_m  numeric(10, 1),

    -- Provenance
    publisher_updated_at    timestamptz,
    retrieved_at            timestamptz NOT NULL,

    -- A fixture always has an instant. A program may have no weekday: 140 of
    -- the 530 AAA Play activities state none, and "days not stated" is a
    -- statement the page can make, whereas a dropped row is not.
    CONSTRAINT event_kind_has_time CHECK (
        kind <> 'fixture' OR starts_at IS NOT NULL
    ),
    CONSTRAINT event_match_basis_known CHECK (
        venue_match_basis IN ('name_and_distance', 'distance_only', 'name_only', 'none')
    ),
    CONSTRAINT event_match_paired CHECK (
        (venue_id IS NULL) = (venue_match_basis = 'none')
    ),
    CONSTRAINT event_geom_is_point CHECK (
        venue_geom IS NULL OR ST_GeometryType(venue_geom) = 'ST_Point'
    ),
    CONSTRAINT event_price_known CHECK (price IS NULL OR price IN ('free', 'paid'))
);

CREATE INDEX event_starts_at_idx      ON event (starts_at);
CREATE INDEX event_sport_starts_idx   ON event (sport, starts_at);
CREATE INDEX event_venue_idx          ON event (venue_id);
CREATE INDEX event_kind_status_idx    ON event (kind, status);
CREATE INDEX event_geom_idx           ON event USING gist (venue_geom);
CREATE INDEX event_weekdays_idx       ON event USING gin (weekdays);

COMMENT ON TABLE event IS
    'One row per listable thing on the events page: a dated fixture or a recurring program. Access status is never stored here; it is read through venue_id at request time so an event and its venue page cannot disagree.';
COMMENT ON COLUMN event.venue_match_basis IS
    'How venue_id was decided: name_and_distance (within 150 m and trigram similarity > 0.3), distance_only (within 25 m), name_only (similarity >= 0.6 within 400 m), none. Audit trail for the matcher; revisit thresholds without a reload.';
COMMENT ON COLUMN event.access_needs IS
    'Publisher-entered tags. An empty array is no published information about who the program suits, never a statement that it is unsuitable. Never a predicate for listing.';


-- The per-source staleness threshold (HLD principle 3, AC3.3.3). The API
-- falls back to its configured default while this is NULL.
ALTER TABLE source
    ADD COLUMN stale_after_days integer;

COMMENT ON COLUMN source.stale_after_days IS
    'Days after publisher_last_updated beyond which every fact from this source is marked possibly out of date. From the register card cadence. NULL = use the API default.';

COMMIT;
