-- SportAble Melbourne - serving store schema
-- sql/001_schema.sql
--
-- PostgreSQL 15+ and PostGIS 3.3+
-- Geometry uses EPSG:7844 (GDA2020).
-- Distances are calculated using geography so the result is in metres.
--
-- Accessibility is stored as separate statuses instead of one overall score.
-- This means each accessibility feature can be traced back to its source.
--
-- Status fields use three values:
-- confirmed
-- not_available
-- no_published_information
--
-- source_id and load_run_id are kept on fact tables for provenance.

CREATE EXTENSION IF NOT EXISTS postgis;


-- Enum types

CREATE TYPE publication_status AS ENUM (
    'confirmed',
    'not_available',
    'no_published_information'
);

CREATE TYPE access_link AS ENUM (
    'arrive',
    'enter',
    'toilet',
    'change',
    'play'
);

CREATE TYPE amenity_kind AS ENUM (
    'accessible_toilet',
    'accessible_parking',
    'accessible_transport_stop',
    'accessible_change_facility'
);

CREATE TYPE quarantine_reason AS ENUM (
    'COORD_MISSING',
    'COORD_INVALID',
    'COORD_TRANSPOSED',
    'OUTSIDE_SCOPE',
    'SCHEMA_VIOLATION',
    'DUPLICATE_KEY',
    'REQUIRED_FIELD_NULL'
);

CREATE TYPE status_basis AS ENUM (
    'publisher_attribute',
    'spatial_proximity',
    'not_published'
);


-- Source register and load information

CREATE TABLE source (
    source_id            text PRIMARY KEY,
    name                 text NOT NULL,
    publisher            text NOT NULL,
    licence_name         text NOT NULL,
    licence_url          text NOT NULL,
    attribution_text     text NOT NULL,
    landing_page         text,
    publisher_scope      text NOT NULL,
    publisher_last_updated date,
    iteration_1          boolean NOT NULL DEFAULT true,
    CONSTRAINT source_id_format CHECK (source_id ~ '^DS-[0-9]{2}$')
);

COMMENT ON TABLE source IS
    'Source register used to keep dataset and licence information.';


CREATE TABLE load_run (
    load_run_id          bigserial PRIMARY KEY,
    started_at           timestamptz NOT NULL DEFAULT now(),
    completed_at         timestamptz,
    dt_partition         date NOT NULL,
    source_id            text NOT NULL REFERENCES source(source_id),
    raw_object_key       text NOT NULL,
    raw_sha256           char(64) NOT NULL,
    rows_read            integer,
    rows_loaded          integer,
    rows_quarantined     integer,
    outcome              text,
    CONSTRAINT raw_sha256_hex CHECK (raw_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX load_run_source_dt_idx ON load_run (source_id, dt_partition DESC);

COMMENT ON COLUMN load_run.raw_sha256 IS
    'SHA-256 hash of the raw object used for this load.';


CREATE TABLE quarantine (
    quarantine_id        bigserial PRIMARY KEY,
    load_run_id          bigint NOT NULL REFERENCES load_run(load_run_id),
    source_id            text NOT NULL REFERENCES source(source_id),
    natural_key          text,
    reason               quarantine_reason NOT NULL,
    detail               text,
    payload              jsonb NOT NULL,
    quarantined_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX quarantine_run_reason_idx ON quarantine (load_run_id, reason);


-- Geography

CREATE TABLE lga (
    lga_code             text PRIMARY KEY,
    lga_name             text NOT NULL,
    lga_name_normalised  text NOT NULL,
    in_greater_melbourne boolean NOT NULL,
    source_id            text NOT NULL REFERENCES source(source_id),
    geom                 geometry(MultiPolygon, 7844) NOT NULL
);

CREATE INDEX lga_geom_idx ON lga USING gist (geom);
CREATE INDEX lga_gm_idx   ON lga (in_greater_melbourne) WHERE in_greater_melbourne;

COMMENT ON TABLE lga IS
    'LGA boundaries used to define the Greater Melbourne project area.';


CREATE TABLE suburb (
    suburb_code          text PRIMARY KEY,
    suburb_name          text NOT NULL,
    source_id            text NOT NULL REFERENCES source(source_id),
    geom                 geometry(MultiPolygon, 7844) NOT NULL
);

CREATE INDEX suburb_geom_idx ON suburb USING gist (geom);
CREATE INDEX suburb_name_idx ON suburb (lower(suburb_name));

COMMENT ON TABLE suburb IS
    'Suburb and locality boundaries used for display and searching.';


-- Venues

CREATE TABLE venue (
    venue_id             text PRIMARY KEY,
    source_id            text NOT NULL REFERENCES source(source_id),
    load_run_id          bigint NOT NULL REFERENCES load_run(load_run_id),

    name                 text NOT NULL,
    full_address         text,
    suburb_name          text,
    postcode             text,
    lga_code             text REFERENCES lga(lga_code),
    lga_name             text,

    geom                 geometry(Point, 7844) NOT NULL,

    ownership            text,
    purpose              text,

    -- These come directly from the venue source.
    -- They are kept as separate statuses rather than combined into a score.
    onsite_accessible_toilet   publication_status NOT NULL,
    onsite_accessible_parking  publication_status NOT NULL,

    -- This is only the description from the source.
    -- It does not mean the changeroom is accessible.
    changeroom_description     text,

    retrieved_at         timestamptz NOT NULL,
    CONSTRAINT venue_geom_is_point CHECK (ST_GeometryType(geom) = 'ST_Point')
);

CREATE INDEX venue_geom_idx     ON venue USING gist (geom);
CREATE INDEX venue_lga_idx      ON venue (lga_code);
CREATE INDEX venue_name_idx     ON venue USING gin (to_tsvector('english', name));
CREATE INDEX venue_postcode_idx ON venue (postcode);

COMMENT ON COLUMN venue.onsite_accessible_toilet IS
    'Accessibility status from the DS-01 Facility Features field.';

COMMENT ON COLUMN venue.changeroom_description IS
    'Description of changerooms from the source. This is not used as an accessibility status.';


-- Sports linked to each venue

CREATE TABLE venue_sport (
    venue_sport_id       bigserial PRIMARY KEY,
    venue_id             text NOT NULL REFERENCES venue(venue_id) ON DELETE CASCADE,
    sport                text NOT NULL,
    court_count          integer,
    surface_type         text,

    UNIQUE (venue_id, sport, surface_type)
);

CREATE INDEX venue_sport_sport_idx ON venue_sport (lower(sport));
CREATE INDEX venue_sport_venue_idx ON venue_sport (venue_id);

COMMENT ON COLUMN venue_sport.surface_type IS
    'Surface description from the source. It is not treated as an accessibility value.';


-- Amenities

CREATE TABLE amenity (
    amenity_id           text PRIMARY KEY,
    source_id             text NOT NULL REFERENCES source(source_id),
    load_run_id           bigint NOT NULL REFERENCES load_run(load_run_id),

    kind                 amenity_kind NOT NULL,
    name                 text,
    geom                 geometry(Point, 7844) NOT NULL,

    key_required         boolean,
    mlak_24h             boolean,
    payment_required     boolean,
    opening_hours        text,

    access_note          text,
    facility_note        text,

    is_inside_venue      boolean NOT NULL DEFAULT false,
    key_is_derived       boolean NOT NULL DEFAULT false,

    retrieved_at         timestamptz NOT NULL,
    CONSTRAINT amenity_geom_is_point CHECK (ST_GeometryType(geom) = 'ST_Point')
);

CREATE INDEX amenity_geom_idx      ON amenity USING gist (geom);
CREATE INDEX amenity_kind_geom_idx ON amenity USING gist (geom) INCLUDE (kind);
CREATE INDEX amenity_kind_idx      ON amenity (kind);

COMMENT ON TABLE amenity IS
    'Accessible amenities from the different source datasets.';


-- Venue accessibility status based on nearby amenities

CREATE TABLE venue_amenity_status (
    venue_id             text NOT NULL REFERENCES venue(venue_id) ON DELETE CASCADE,
    kind                 amenity_kind NOT NULL,
    load_run_id          bigint NOT NULL REFERENCES load_run(load_run_id),

    status               publication_status NOT NULL,
    basis                status_basis NOT NULL,

    nearest_amenity_id   text REFERENCES amenity(amenity_id),
    distance_m           numeric(10, 1),

    within_250m          boolean NOT NULL DEFAULT false,
    within_500m          boolean NOT NULL DEFAULT false,
    within_1000m         boolean NOT NULL DEFAULT false,

    computed_at          timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (venue_id, kind),

    CONSTRAINT confirmed_has_evidence CHECK (
        status <> 'confirmed'
        OR basis = 'publisher_attribute'
        OR (nearest_amenity_id IS NOT NULL AND distance_m IS NOT NULL)
    ),

    CONSTRAINT bands_match_distance CHECK (
        (within_250m  = (distance_m IS NOT NULL AND distance_m <=  250))
        AND (within_500m  = (distance_m IS NOT NULL AND distance_m <=  500))
        AND (within_1000m = (distance_m IS NOT NULL AND distance_m <= 1000))
    )
);

CREATE INDEX vas_kind_250_idx
    ON venue_amenity_status (kind)
    WHERE within_250m;

CREATE INDEX vas_kind_500_idx
    ON venue_amenity_status (kind)
    WHERE within_500m;

CREATE INDEX vas_kind_1000_idx
    ON venue_amenity_status (kind)
    WHERE within_1000m;

CREATE INDEX vas_venue_idx
    ON venue_amenity_status (venue_id);

COMMENT ON COLUMN venue_amenity_status.distance_m IS
    'Straight-line distance in metres. This is not walking distance.';

COMMENT ON CONSTRAINT bands_match_distance ON venue_amenity_status IS
    'Makes sure the distance bands match the stored distance.';


-- Access chain for each venue

CREATE TABLE venue_access_chain (
    venue_id             text NOT NULL REFERENCES venue(venue_id) ON DELETE CASCADE,
    link                 access_link NOT NULL,
    status               publication_status NOT NULL,
    basis                status_basis NOT NULL,
    detail               text,
    computed_at          timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (venue_id, link)
);

CREATE INDEX vac_link_status_idx
    ON venue_access_chain (link, status);

COMMENT ON TABLE venue_access_chain IS
    'Stores the five access links for each venue.';


-- Venue search/read model

CREATE VIEW venue_card AS
SELECT
    v.venue_id,
    v.name,
    v.suburb_name,
    v.postcode,
    v.lga_name,
    v.geom,
    v.onsite_accessible_toilet,
    v.onsite_accessible_parking,
    v.changeroom_description,
    array_remove(array_agg(DISTINCT vs.sport), NULL)        AS sports,
    array_remove(array_agg(DISTINCT vs.surface_type), NULL) AS surface_types,
    max(CASE WHEN s.kind = 'accessible_toilet'          THEN s.distance_m END) AS toilet_distance_m,
    max(CASE WHEN s.kind = 'accessible_parking'         THEN s.distance_m END) AS parking_distance_m,
    max(CASE WHEN s.kind = 'accessible_transport_stop'  THEN s.distance_m END) AS transport_distance_m,
    max(CASE WHEN s.kind = 'accessible_change_facility' THEN s.distance_m END) AS change_distance_m,
    max(CASE WHEN s.kind = 'accessible_toilet'          THEN s.status::text END) AS toilet_status,
    max(CASE WHEN s.kind = 'accessible_parking'         THEN s.status::text END) AS parking_status,
    max(CASE WHEN s.kind = 'accessible_transport_stop'  THEN s.status::text END) AS transport_status,
    max(CASE WHEN s.kind = 'accessible_change_facility' THEN s.status::text END) AS change_status
FROM venue v
LEFT JOIN venue_sport vs
    ON vs.venue_id = v.venue_id
LEFT JOIN venue_amenity_status s
    ON s.venue_id = v.venue_id
GROUP BY v.venue_id;

COMMENT ON VIEW venue_card IS
    'View used by the venue search and venue page.';
