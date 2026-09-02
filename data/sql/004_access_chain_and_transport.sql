-- sql/004_access_chain_and_transport.sql
--
-- Three changes, all forced by the same finding: the read model the frontend
-- consumes and the access chain the schema stores were not the same shape.
--
-- 1. access_link splits 'arrive' into 'arrive_parking' and 'arrive_transport'.
--
--    The frontend renders four facility tiles: accessible toilet, accessible
--    parking, step-free transport stop, accessible change facility. The chain
--    stored five links and collapsed accessible parking and step-free transport
--    into a single 'arrive'. That collapse is a composite: two facts published
--    by two different sources, reduced to one status, with no way to recover
--    which one answered. The project prohibits composites everywhere else and
--    this is no exception. The access chain remains five stages in the
--    narrative; arrive is now recorded as the two independent facts that
--    actually populate it.
--
--    Every chain row is rebuilt by status_builder on every run, so the existing
--    rows are truncated rather than migrated. Nothing is lost that the next
--    build does not immediately replace.
--
-- 2. venue_access_chain gains a 'kind' column naming which facility tile the
--    link drives, or NULL for the two links no dataset answers. AC2.1.5 needs
--    exactly that split to generate the 'what this cannot tell you' section.
--
-- 3. amenity gains the three DS-03 columns. Transport stops are the fourth
--    amenity kind and had no transform and no columns; without them the
--    step-free transport filter has nothing behind it and the tile can only
--    ever read 'no published information'.

BEGIN;


-- 1. Access link vocabulary

-- Rebuilt on every status_builder run, so truncation is safe and is the only
-- way to split one stored row into two.
TRUNCATE TABLE venue_access_chain;

ALTER TYPE access_link RENAME TO access_link_v1;

CREATE TYPE access_link AS ENUM (
    'arrive_parking',
    'arrive_transport',
    'enter',
    'toilet',
    'change',
    'play'
);

ALTER TABLE venue_access_chain
    ALTER COLUMN link TYPE access_link
    USING link::text::access_link;

DROP TYPE access_link_v1;

COMMENT ON TYPE access_link IS
    'The five stages of the access chain. Arrive is recorded as two links because it is published by two independent sources, and merging them would be a composite status.';


-- 2. Which tile a link drives

ALTER TABLE venue_access_chain
    ADD COLUMN kind amenity_kind;

COMMENT ON COLUMN venue_access_chain.kind IS
    'The facility tile this link is rendered as. NULL for enter and play, which no registered dataset publishes and which appear only in the limits section of the venue card.';

COMMENT ON TABLE venue_access_chain IS
    'The access chain for each venue. Four links carry a kind and are rendered as facility tiles; enter and play carry no kind and are always no_published_information.';


-- 3. Transport stop attributes on amenity

ALTER TABLE amenity
    ADD COLUMN transport_mode text,
    ADD COLUMN wheelchair_boarding smallint,
    ADD COLUMN stop_code text;

COMMENT ON COLUMN amenity.transport_mode IS
    'The PTV mode feed this stop came from, for example Metropolitan train. NULL for every amenity that is not a transport stop.';

COMMENT ON COLUMN amenity.wheelchair_boarding IS
    'The published GTFS wheelchair_boarding value carried through verbatim. 1 is confirmed, 2 is a published absence, 0 or NULL is no published information. Only rows with 1 are loaded as accessible_transport_stop amenities, so in practice this column is 1 for every loaded stop and exists so the published value is never lost.';

COMMENT ON COLUMN amenity.stop_code IS
    'The publisher stop code where one is published. Display only.';

ALTER TABLE amenity
    ADD CONSTRAINT transport_columns_only_on_stops CHECK (
        kind = 'accessible_transport_stop'
        OR (transport_mode IS NULL AND wheelchair_boarding IS NULL)
    );


-- 4. Provenance on the derived status

-- AC1.3.2 requires the name of the source that recorded a facility to be shown
-- beside every confirmed status. The status table recorded which amenity was
-- nearest but not which source published it, so the API had nothing to render.
ALTER TABLE venue_amenity_status
    ADD COLUMN source_id text REFERENCES source(source_id);

COMMENT ON COLUMN venue_amenity_status.source_id IS
    'The source that produced this status: the venue source when the basis is publisher_attribute, the amenity source when it is spatial_proximity, NULL when nothing published it.';


-- 5. Postal areas

-- The search box accepts a postcode and the results header names the point
-- distances were measured from. DS-07 is ABS Suburbs and Localities and
-- publishes no postcode, so nothing in the register could resolve '3000' to a
-- coordinate. DS-08 supplies the missing layer.
CREATE TABLE postal_area (
    poa_code             text PRIMARY KEY,
    poa_name             text NOT NULL,
    source_id            text NOT NULL REFERENCES source(source_id),
    geom                 geometry(MultiPolygon, 7844) NOT NULL
);

CREATE INDEX postal_area_geom_idx ON postal_area USING gist (geom);
CREATE INDEX postal_area_code_idx ON postal_area (poa_code);

COMMENT ON TABLE postal_area IS
    'ABS Postal Areas, used only to resolve a typed postcode to a search point. Postal areas approximate Australia Post postcodes and are not authoritative for delivery.';

COMMIT;
