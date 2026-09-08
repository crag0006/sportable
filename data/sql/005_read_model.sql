-- sql/005_read_model.sql
--
-- The read model the API serves from.
--
-- venue_card was a plain view doing array_agg and GROUP BY across the whole
-- venue table on every request, on a db.t4g.micro behind a VPC-attached Lambda.
-- The architecture's stated position is that access status is derived once in
-- the pipeline and not at request time; a view that re-aggregates per request
-- contradicts it and will not hold the three-second budget in AC1.1.5.
--
-- All three objects below are materialised and refreshed at the end of the
-- pipeline by status_builder.refresh_read_model(). Nothing here derives a new
-- fact. Every column is carried from a table that already holds it.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- 1. Venue card

-- The old view cannot be extended in place because a materialised view cannot
-- replace a view of the same name.
DROP VIEW IF EXISTS venue_card;

CREATE MATERIALIZED VIEW venue_card AS
SELECT
    v.venue_id,
    v.name,
    v.full_address,
    v.suburb_name,
    v.postcode,
    v.lga_code,
    v.lga_name,
    v.geom,
    v.ownership,
    v.purpose,
    v.changeroom_description,
    v.retrieved_at,

    coalesce(s.sports, ARRAY[]::text[])         AS sports,
    coalesce(s.surface_types, ARRAY[]::text[])  AS surface_types,

    -- Accessible toilet
    t.status::text        AS toilet_status,
    t.basis::text         AS toilet_basis,
    t.distance_m          AS toilet_distance_m,
    t.within_250m         AS toilet_within_250m,
    t.within_500m         AS toilet_within_500m,
    t.within_1000m        AS toilet_within_1000m,
    t.source_id           AS toilet_source_id,
    at.name               AS toilet_amenity_name,
    at.is_inside_venue    AS toilet_is_inside_venue,
    at.opening_hours      AS toilet_opening_hours,
    at.key_required       AS toilet_key_required,
    at.mlak_24h           AS toilet_mlak_24h,
    at.payment_required   AS toilet_payment_required,
    at.access_note        AS toilet_access_note,

    -- Accessible parking
    p.status::text        AS parking_status,
    p.basis::text         AS parking_basis,
    p.distance_m          AS parking_distance_m,
    p.within_250m         AS parking_within_250m,
    p.within_500m         AS parking_within_500m,
    p.within_1000m        AS parking_within_1000m,
    p.source_id           AS parking_source_id,
    ap.name               AS parking_amenity_name,
    ap.is_inside_venue    AS parking_is_inside_venue,

    -- Step-free transport stop
    r.status::text        AS transport_status,
    r.basis::text         AS transport_basis,
    r.distance_m          AS transport_distance_m,
    r.within_250m         AS transport_within_250m,
    r.within_500m         AS transport_within_500m,
    r.within_1000m        AS transport_within_1000m,
    r.source_id           AS transport_source_id,
    ar.name               AS transport_amenity_name,
    ar.transport_mode     AS transport_mode,

    -- Accessible change facility
    c.status::text        AS change_status,
    c.basis::text         AS change_basis,
    c.distance_m          AS change_distance_m,
    c.within_250m         AS change_within_250m,
    c.within_500m         AS change_within_500m,
    c.within_1000m        AS change_within_1000m,
    c.source_id           AS change_source_id,
    ac.name               AS change_amenity_name,
    ac.is_inside_venue    AS change_is_inside_venue,
    ac.changing_places    AS change_is_changing_places,
    ac.has_shower         AS change_has_shower,
    ac.opening_hours      AS change_opening_hours

FROM venue v

LEFT JOIN LATERAL (
    SELECT array_remove(array_agg(DISTINCT vs.sport), NULL)        AS sports,
           array_remove(array_agg(DISTINCT vs.surface_type), NULL) AS surface_types
      FROM venue_sport vs
     WHERE vs.venue_id = v.venue_id
) s ON true

LEFT JOIN venue_amenity_status t
    ON t.venue_id = v.venue_id AND t.kind = 'accessible_toilet'
LEFT JOIN amenity at ON at.amenity_id = t.nearest_amenity_id

LEFT JOIN venue_amenity_status p
    ON p.venue_id = v.venue_id AND p.kind = 'accessible_parking'
LEFT JOIN amenity ap ON ap.amenity_id = p.nearest_amenity_id

LEFT JOIN venue_amenity_status r
    ON r.venue_id = v.venue_id AND r.kind = 'accessible_transport_stop'
LEFT JOIN amenity ar ON ar.amenity_id = r.nearest_amenity_id

LEFT JOIN venue_amenity_status c
    ON c.venue_id = v.venue_id AND c.kind = 'accessible_change_facility'
LEFT JOIN amenity ac ON ac.amenity_id = c.nearest_amenity_id;

-- A unique index is required for REFRESH MATERIALIZED VIEW CONCURRENTLY, which
-- is what keeps the API serving during a pipeline run.
CREATE UNIQUE INDEX venue_card_pk_idx   ON venue_card (venue_id);
CREATE INDEX venue_card_geom_idx        ON venue_card USING gist (geom);
CREATE INDEX venue_card_sports_idx      ON venue_card USING gin (sports);
CREATE INDEX venue_card_postcode_idx    ON venue_card (postcode);
CREATE INDEX venue_card_lga_idx         ON venue_card (lga_code);

COMMENT ON MATERIALIZED VIEW venue_card IS
    'The read model for venue search and the venue card. Refreshed by the pipeline, never computed at request time. A status column is the status at the 1 km ceiling; the API applies the user distance limit using the within_250m, within_500m and within_1000m flags rather than reading status directly.';


-- 2. Sport vocabulary

-- AC1.1.1 requires the sport field to offer only sports that exist in the venue
-- data. There was no such list, so the field could accept anything and return
-- nothing.
CREATE MATERIALIZED VIEW sport_vocabulary AS
SELECT vs.sport,
       count(DISTINCT vs.venue_id) AS venue_count
  FROM venue_sport vs
  JOIN venue v ON v.venue_id = vs.venue_id
 WHERE vs.sport IS NOT NULL
 GROUP BY vs.sport;

CREATE UNIQUE INDEX sport_vocabulary_pk_idx ON sport_vocabulary (sport);
CREATE INDEX sport_vocabulary_trgm_idx
    ON sport_vocabulary USING gin (lower(sport) gin_trgm_ops);

COMMENT ON MATERIALIZED VIEW sport_vocabulary IS
    'Distinct sports present in loaded venues, with the number of venues offering each. Backs the sport typeahead; a sport absent from this list has no venues and must not be offered.';


-- 3. Search location resolver

-- AC1.1.3 requires the point distances are measured from to be named on screen,
-- because a suburb is an area and not a point. AC1.1.4 requires a location
-- outside Greater Melbourne to be told apart from a location that was not
-- recognised at all, which needs the in_greater_melbourne flag below rather
-- than an empty result.
CREATE MATERIALIZED VIEW search_location AS
SELECT
    'suburb'                              AS location_kind,
    sb.suburb_code                        AS code,
    sb.suburb_name                        AS label,
    sb.suburb_name                        AS display_name,
    sb.source_id,
    ST_PointOnSurface(sb.geom)            AS search_point,
    sb.geom,
    EXISTS (
        SELECT 1 FROM lga l
         WHERE l.in_greater_melbourne
           AND ST_Intersects(l.geom, sb.geom)
    )                                     AS in_greater_melbourne
FROM suburb sb

UNION ALL

SELECT
    'postcode'                            AS location_kind,
    pa.poa_code                           AS code,
    pa.poa_code                           AS label,
    'postcode ' || pa.poa_code            AS display_name,
    pa.source_id,
    ST_PointOnSurface(pa.geom)            AS search_point,
    pa.geom,
    EXISTS (
        SELECT 1 FROM lga l
         WHERE l.in_greater_melbourne
           AND ST_Intersects(l.geom, pa.geom)
    )                                     AS in_greater_melbourne
FROM postal_area pa;

CREATE UNIQUE INDEX search_location_pk_idx
    ON search_location (location_kind, code);
CREATE INDEX search_location_point_idx
    ON search_location USING gist (search_point);
CREATE INDEX search_location_label_trgm_idx
    ON search_location USING gin (lower(label) gin_trgm_ops);
CREATE INDEX search_location_gm_idx
    ON search_location (in_greater_melbourne) WHERE in_greater_melbourne;

COMMENT ON MATERIALIZED VIEW search_location IS
    'Suburbs and postal areas resolvable from the search box, each with the point distances are measured from. ST_PointOnSurface rather than ST_Centroid, because the centroid of a crescent-shaped or multipart locality can fall outside it.';

COMMENT ON COLUMN search_location.in_greater_melbourne IS
    'False for a real Victorian or Australian place outside the 31 councils. The API uses this to say the area is not covered rather than returning an empty result, which AC1.1.4 forbids.';


-- 4. Facility detail

-- One row per venue per tile, with the provenance the acceptance criteria
-- require printed beside every status. Every endpoint that shows a facility
-- reads this, so the source name on the results list and the source name on the
-- venue card cannot drift apart by being assembled twice.
--
-- Not materialised. It is only ever queried for a single venue or for the
-- handful of venues on one page of results.

CREATE VIEW venue_facility_detail AS
SELECT
    s.venue_id,
    s.kind::text                                        AS kind,
    s.status::text                                      AS status,
    s.basis::text                                       AS basis,
    s.distance_m,
    s.within_250m,
    s.within_500m,
    s.within_1000m,

    s.source_id,
    src.name                                            AS source_name,
    src.attribution_text,
    src.publisher_last_updated                          AS source_last_updated,

    a.amenity_id,
    a.name                                              AS amenity_name,
    a.address                                           AS amenity_address,

    -- AC2.1.3. The third case is a statement, not a blank.
    CASE
        WHEN s.basis = 'publisher_attribute'  THEN 'at the venue'
        WHEN a.is_inside_venue                THEN 'at the venue'
        WHEN a.amenity_id IS NOT NULL         THEN 'a separate public facility nearby'
        ELSE 'no source records whether this is inside the venue or nearby'
    END                                                 AS location_relative_to_venue,

    -- AC2.1.4. A null here means the source recorded nothing, and the interface
    -- has to say that rather than leave the field empty.
    a.opening_hours,
    a.key_required,
    a.mlak_24h,
    a.payment_required,
    (a.amenity_id IS NOT NULL AND a.opening_hours IS NULL) AS opening_hours_unrecorded,
    (a.amenity_id IS NOT NULL AND a.key_required  IS NULL) AS key_requirement_unrecorded,

    a.changing_places,
    a.has_shower,
    a.ambulant,
    a.left_hand_transfer,
    a.right_hand_transfer,
    a.access_note,
    a.facility_note,
    a.transport_mode,
    a.wheelchair_boarding

FROM venue_amenity_status s
LEFT JOIN amenity a ON a.amenity_id = s.nearest_amenity_id
LEFT JOIN source  src ON src.source_id = s.source_id;

COMMENT ON VIEW venue_facility_detail IS
    'One row per venue per facility tile, carrying the source name and its last-updated date required beside every confirmed status by AC1.3.2, the inside-or-nearby statement required by AC2.1.3, and the explicit unrecorded flags required by AC2.1.4.';

COMMIT;
