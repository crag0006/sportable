-- sql/006_route_corridor.sql
--
-- The directions view. Everything else on the two screens reads a status that
-- was derived once in the pipeline; this one cannot be, because the corridor
-- depends on a starting point supplied at request time. AC2.2.1 says so
-- explicitly: the user is asked for a starting point before any list is
-- produced, and the page explains that the facilities on the way depend on
-- where the journey begins.
--
-- So this migration adds no tables. It adds two functions that run against the
-- amenity table at request time, and the only thing they need from outside is
-- the route line itself.
--
-- Nothing about the route is stored. DS-05's card records that nothing
-- openrouteservice returns is persisted and no facility status ever traces to
-- it. These functions take the geometry as an argument and keep it for the
-- length of the query.
--
--
-- ON THE SRID, WHICH IS THE ONE THING THAT WILL BITE
--
-- openrouteservice returns GeoJSON in EPSG:4326 (WGS84). The serving store is
-- EPSG:7844 (GDA2020). They are not the same datum, but at Melbourne latitudes
-- they differ by roughly 1.8 metres, and ST_Transform between them needs grid
-- files that are not installed on RDS by default.
--
-- The corridor is 400 metres wide. A 1.8 metre datum difference cannot change
-- which amenities fall inside it. So the caller declares the route as 7844
-- rather than transforming it:
--
--     ST_SetSRID(ST_GeomFromGeoJSON(:route_geojson), 7844)
--
-- That is a deliberate approximation and it is recorded here rather than
-- buried in the API. It is fine for a corridor and it would not be fine for
-- anything that reported a position to sub-metre precision. Nothing here does.


BEGIN;


-- 1. The facilities on the way

CREATE OR REPLACE FUNCTION route_corridor(
    route      geometry,
    corridor_m numeric DEFAULT 400,
    kinds      amenity_kind[] DEFAULT ARRAY[
                   'accessible_toilet',
                   'accessible_parking',
                   'accessible_transport_stop'
               ]::amenity_kind[]
)
RETURNS TABLE (
    sequence                integer,
    amenity_id              text,
    kind                    text,
    name                    text,
    address                 text,
    latitude                double precision,
    longitude               double precision,
    distance_from_route_m   numeric,
    position_along_route    numeric,
    source_id               text,
    source_name             text,
    source_last_updated     date,
    attribution_text        text,
    opening_hours           text,
    opening_hours_unrecorded boolean,
    key_required            boolean,
    mlak_24h                boolean,
    key_requirement_unrecorded boolean,
    payment_required        boolean,
    access_note             text,
    transport_mode          text,
    changing_places         boolean
) AS $$
    SELECT
        (row_number() OVER (
            ORDER BY ST_LineLocatePoint(
                ST_LineMerge(route),
                ST_ClosestPoint(ST_LineMerge(route), a.geom)
            )
        ))::integer                                     AS sequence,

        a.amenity_id,
        a.kind::text,
        a.name,
        a.address,
        ST_Y(a.geom)::double precision                  AS latitude,
        ST_X(a.geom)::double precision                  AS longitude,

        round(ST_Distance(a.geom::geography, route::geography)::numeric, 1)
                                                        AS distance_from_route_m,

        -- 0 at the starting point, 1 at the venue. This is what puts the list
        -- "in the order they occur along the journey" rather than in order of
        -- distance from the line, which would interleave the whole route.
        round(ST_LineLocatePoint(
            ST_LineMerge(route),
            ST_ClosestPoint(ST_LineMerge(route), a.geom)
        )::numeric, 4)                                  AS position_along_route,

        a.source_id,
        s.name                                          AS source_name,
        s.publisher_last_updated                        AS source_last_updated,
        s.attribution_text,

        a.opening_hours,
        (a.opening_hours IS NULL)                       AS opening_hours_unrecorded,
        a.key_required,
        a.mlak_24h,
        (a.key_required IS NULL)                        AS key_requirement_unrecorded,
        a.payment_required,
        a.access_note,
        a.transport_mode,
        a.changing_places

    FROM amenity a
    LEFT JOIN source s ON s.source_id = a.source_id
    WHERE a.kind = ANY (kinds)
      AND ST_DWithin(a.geom::geography, route::geography, corridor_m)
    ORDER BY position_along_route;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION route_corridor IS
    'AC2.2.2 and AC2.2.3. The accessible facilities within corridor_m of the path, in the order they occur along the journey, each with the source that recorded it and the date that source was last updated. Ordering is by ST_LineLocatePoint along the route, not by distance from it. Stores nothing.';


-- 2. The types that found nothing

-- AC2.2.4: where no accessible facility of a given type falls within the
-- stated distance, the site says so plainly for that type rather than leaving
-- the section empty and letting the absence read as an answer.
--
-- That cannot be done by iterating the rows the first function returned,
-- because a type with no facilities produces no rows to iterate. This returns
-- one row per requested type whether or not anything was found, so the empty
-- case is a value the interface renders rather than a branch it has to
-- remember to write.

CREATE OR REPLACE FUNCTION route_corridor_summary(
    route      geometry,
    corridor_m numeric DEFAULT 400,
    kinds      amenity_kind[] DEFAULT ARRAY[
                   'accessible_toilet',
                   'accessible_parking',
                   'accessible_transport_stop'
               ]::amenity_kind[]
)
RETURNS TABLE (
    kind          text,
    found         integer,
    nearest_m     numeric
) AS $$
    SELECT
        k::text                                         AS kind,
        count(a.amenity_id)::integer                    AS found,
        round(min(ST_Distance(a.geom::geography, route::geography))::numeric, 1)
                                                        AS nearest_m
    FROM unnest(kinds) AS k
    LEFT JOIN amenity a
           ON a.kind = k
          AND ST_DWithin(a.geom::geography, route::geography, corridor_m)
    GROUP BY k
    ORDER BY k::text;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION route_corridor_summary IS
    'One row per facility type requested, including the types that found nothing. found = 0 is the case AC2.4 requires the interface to state in words. nearest_m is NULL when nothing of that type is inside the corridor.';


COMMIT;
