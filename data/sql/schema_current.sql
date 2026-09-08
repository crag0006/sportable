--
-- SportAble Melbourne - consolidated schema, READ-ONLY REFERENCE
--
-- Generated 02 September 2026 by pg_dump from a clean database with migrations
-- 001 to 007 applied in order. PostgreSQL 16.15, PostGIS 3.4.


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- Name: access_link; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.access_link AS ENUM (
    'arrive_parking',
    'arrive_transport',
    'enter',
    'toilet',
    'change',
    'play'
);


--
-- Name: TYPE access_link; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.access_link IS 'The five stages of the access chain. Arrive is recorded as two links because it is published by two independent sources, and merging them would be a composite status.';


--
-- Name: amenity_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.amenity_kind AS ENUM (
    'accessible_toilet',
    'accessible_parking',
    'accessible_transport_stop',
    'accessible_change_facility'
);


--
-- Name: publication_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.publication_status AS ENUM (
    'confirmed',
    'not_available',
    'no_published_information'
);


--
-- Name: quarantine_reason; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.quarantine_reason AS ENUM (
    'COORD_MISSING',
    'COORD_INVALID',
    'COORD_TRANSPOSED',
    'OUTSIDE_SCOPE',
    'SCHEMA_VIOLATION',
    'DUPLICATE_KEY',
    'REQUIRED_FIELD_NULL'
);


--
-- Name: status_basis; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.status_basis AS ENUM (
    'publisher_attribute',
    'spatial_proximity',
    'not_published'
);


--
-- Name: route_corridor(public.geometry, numeric, public.amenity_kind[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.route_corridor(route public.geometry, corridor_m numeric DEFAULT 400, kinds public.amenity_kind[] DEFAULT ARRAY['accessible_toilet'::public.amenity_kind, 'accessible_parking'::public.amenity_kind, 'accessible_transport_stop'::public.amenity_kind]) RETURNS TABLE(sequence integer, amenity_id text, kind text, name text, address text, latitude double precision, longitude double precision, distance_from_route_m numeric, position_along_route numeric, source_id text, source_name text, source_last_updated date, attribution_text text, opening_hours text, opening_hours_unrecorded boolean, key_required boolean, mlak_24h boolean, key_requirement_unrecorded boolean, payment_required boolean, access_note text, transport_mode text, changing_places boolean)
    LANGUAGE sql STABLE
    AS $$
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
$$;


--
-- Name: FUNCTION route_corridor(route public.geometry, corridor_m numeric, kinds public.amenity_kind[]); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.route_corridor(route public.geometry, corridor_m numeric, kinds public.amenity_kind[]) IS 'AC2.2.2 and AC2.2.3. The accessible facilities within corridor_m of the path, in the order they occur along the journey, each with the source that recorded it and the date that source was last updated. Ordering is by ST_LineLocatePoint along the route, not by distance from it. Stores nothing.';


--
-- Name: route_corridor_summary(public.geometry, numeric, public.amenity_kind[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.route_corridor_summary(route public.geometry, corridor_m numeric DEFAULT 400, kinds public.amenity_kind[] DEFAULT ARRAY['accessible_toilet'::public.amenity_kind, 'accessible_parking'::public.amenity_kind, 'accessible_transport_stop'::public.amenity_kind]) RETURNS TABLE(kind text, found integer, nearest_m numeric)
    LANGUAGE sql STABLE
    AS $$
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
$$;


--
-- Name: FUNCTION route_corridor_summary(route public.geometry, corridor_m numeric, kinds public.amenity_kind[]); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.route_corridor_summary(route public.geometry, corridor_m numeric, kinds public.amenity_kind[]) IS 'One row per facility type requested, including the types that found nothing. found = 0 is the case AC2.4 requires the interface to state in words. nearest_m is NULL when nothing of that type is inside the corridor.';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: amenity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.amenity (
    amenity_id text NOT NULL,
    source_id text NOT NULL,
    load_run_id bigint NOT NULL,
    kind public.amenity_kind NOT NULL,
    name text,
    geom public.geometry(Point,7844) NOT NULL,
    key_required boolean,
    mlak_24h boolean,
    payment_required boolean,
    opening_hours text,
    access_note text,
    facility_note text,
    is_inside_venue boolean DEFAULT false NOT NULL,
    key_is_derived boolean DEFAULT false NOT NULL,
    retrieved_at timestamp with time zone NOT NULL,
    changing_places boolean,
    byo_sling boolean,
    has_shower boolean,
    ambulant boolean,
    left_hand_transfer boolean,
    right_hand_transfer boolean,
    accessible_parking_on_site boolean,
    address text,
    transport_mode text,
    wheelchair_boarding smallint,
    stop_code text,
    CONSTRAINT amenity_geom_is_point CHECK ((public.st_geometrytype(geom) = 'ST_Point'::text)),
    CONSTRAINT transport_columns_only_on_stops CHECK (((kind = 'accessible_transport_stop'::public.amenity_kind) OR ((transport_mode IS NULL) AND (wheelchair_boarding IS NULL))))
);


--
-- Name: TABLE amenity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.amenity IS 'Accessible amenities from the different source datasets.';


--
-- Name: COLUMN amenity.changing_places; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amenity.changing_places IS 'True when the source records a Changing Places facility, false for a general adult change facility, and null when the amenity is not a change facility.';


--
-- Name: COLUMN amenity.left_hand_transfer; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amenity.left_hand_transfer IS 'Indicates whether a left-hand transfer is available.';


--
-- Name: COLUMN amenity.accessible_parking_on_site; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amenity.accessible_parking_on_site IS 'Accessible parking recorded at the toilet facility. This is separate from the accessible_parking amenity type.';


--
-- Name: COLUMN amenity.transport_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amenity.transport_mode IS 'The PTV mode feed this stop came from, for example Metropolitan train. NULL for every amenity that is not a transport stop.';


--
-- Name: COLUMN amenity.wheelchair_boarding; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amenity.wheelchair_boarding IS 'The published GTFS wheelchair_boarding value carried through verbatim. 1 is confirmed, 2 is a published absence, 0 or NULL is no published information. Only rows with 1 are loaded as accessible_transport_stop amenities, so in practice this column is 1 for every loaded stop and exists so the published value is never lost.';


--
-- Name: COLUMN amenity.stop_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.amenity.stop_code IS 'The publisher stop code where one is published. Display only.';


--
-- Name: lga; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lga (
    lga_code text NOT NULL,
    lga_name text NOT NULL,
    lga_name_normalised text NOT NULL,
    in_greater_melbourne boolean NOT NULL,
    source_id text NOT NULL,
    geom public.geometry(MultiPolygon,7844) NOT NULL
);


--
-- Name: TABLE lga; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.lga IS 'LGA boundaries used to define the Greater Melbourne project area.';


--
-- Name: load_run; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.load_run (
    load_run_id bigint NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    dt_partition date NOT NULL,
    source_id text NOT NULL,
    raw_object_key text NOT NULL,
    raw_sha256 character(64) NOT NULL,
    rows_read integer,
    rows_loaded integer,
    rows_quarantined integer,
    outcome text,
    rows_outside_scope integer,
    CONSTRAINT raw_sha256_hex CHECK ((raw_sha256 ~ '^[0-9a-f]{64}$'::text))
);


--
-- Name: COLUMN load_run.raw_sha256; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.load_run.raw_sha256 IS 'SHA-256 hash of the raw object used for this load.';


--
-- Name: COLUMN load_run.rows_outside_scope; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.load_run.rows_outside_scope IS 'Rows excluded by the spatial clip because they fall outside the 31 Greater Melbourne councils. Correct behaviour for a state or national source, not a rejection, and deliberately excluded from the quarantine rate.';


--
-- Name: load_run_load_run_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.load_run_load_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: load_run_load_run_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.load_run_load_run_id_seq OWNED BY public.load_run.load_run_id;


--
-- Name: postal_area; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.postal_area (
    poa_code text NOT NULL,
    poa_name text NOT NULL,
    source_id text NOT NULL,
    geom public.geometry(MultiPolygon,7844) NOT NULL
);


--
-- Name: TABLE postal_area; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.postal_area IS 'ABS Postal Areas, used only to resolve a typed postcode to a search point. Postal areas approximate Australia Post postcodes and are not authoritative for delivery.';


--
-- Name: quarantine; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quarantine (
    quarantine_id bigint NOT NULL,
    load_run_id bigint NOT NULL,
    source_id text NOT NULL,
    natural_key text,
    reason public.quarantine_reason NOT NULL,
    detail text,
    payload jsonb NOT NULL,
    quarantined_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: quarantine_quarantine_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quarantine_quarantine_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quarantine_quarantine_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quarantine_quarantine_id_seq OWNED BY public.quarantine.quarantine_id;


--
-- Name: suburb; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.suburb (
    suburb_code text NOT NULL,
    suburb_name text NOT NULL,
    source_id text NOT NULL,
    geom public.geometry(MultiPolygon,7844) NOT NULL
);


--
-- Name: TABLE suburb; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.suburb IS 'Suburb and locality boundaries used for display and searching.';


--
-- Name: search_location; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.search_location AS
 SELECT 'suburb'::text AS location_kind,
    sb.suburb_code AS code,
    sb.suburb_name AS label,
    sb.suburb_name AS display_name,
    sb.source_id,
    public.st_pointonsurface(sb.geom) AS search_point,
    sb.geom,
    (EXISTS ( SELECT 1
           FROM public.lga l
          WHERE (l.in_greater_melbourne AND public.st_intersects(l.geom, sb.geom)))) AS in_greater_melbourne
   FROM public.suburb sb
UNION ALL
 SELECT 'postcode'::text AS location_kind,
    pa.poa_code AS code,
    pa.poa_code AS label,
    ('postcode '::text || pa.poa_code) AS display_name,
    pa.source_id,
    public.st_pointonsurface(pa.geom) AS search_point,
    pa.geom,
    (EXISTS ( SELECT 1
           FROM public.lga l
          WHERE (l.in_greater_melbourne AND public.st_intersects(l.geom, pa.geom)))) AS in_greater_melbourne
   FROM public.postal_area pa
  WITH NO DATA;


--
-- Name: MATERIALIZED VIEW search_location; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON MATERIALIZED VIEW public.search_location IS 'Suburbs and postal areas resolvable from the search box, each with the point distances are measured from. ST_PointOnSurface rather than ST_Centroid, because the centroid of a crescent-shaped or multipart locality can fall outside it.';


--
-- Name: COLUMN search_location.in_greater_melbourne; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.search_location.in_greater_melbourne IS 'False for a real Victorian or Australian place outside the 31 councils. The API uses this to say the area is not covered rather than returning an empty result, which AC1.1.4 forbids.';


--
-- Name: source; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source (
    source_id text NOT NULL,
    name text NOT NULL,
    publisher text NOT NULL,
    licence_name text NOT NULL,
    licence_url text NOT NULL,
    attribution_text text NOT NULL,
    landing_page text,
    publisher_scope text NOT NULL,
    publisher_last_updated date,
    iteration_1 boolean DEFAULT true NOT NULL,
    CONSTRAINT source_id_format CHECK ((source_id ~ '^DS-[0-9]{2}$'::text))
);


--
-- Name: TABLE source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.source IS 'Source register used to keep dataset and licence information.';


--
-- Name: venue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.venue (
    venue_id text NOT NULL,
    source_id text NOT NULL,
    load_run_id bigint NOT NULL,
    name text NOT NULL,
    full_address text,
    suburb_name text,
    postcode text,
    lga_code text,
    lga_name text,
    geom public.geometry(Point,7844) NOT NULL,
    ownership text,
    purpose text,
    onsite_accessible_toilet public.publication_status NOT NULL,
    onsite_accessible_parking public.publication_status NOT NULL,
    changeroom_description text,
    retrieved_at timestamp with time zone NOT NULL,
    CONSTRAINT venue_geom_is_point CHECK ((public.st_geometrytype(geom) = 'ST_Point'::text))
);


--
-- Name: COLUMN venue.onsite_accessible_toilet; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue.onsite_accessible_toilet IS 'Accessibility status from the DS-01 Facility Features field.';


--
-- Name: COLUMN venue.changeroom_description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue.changeroom_description IS 'Description of changerooms from the source. This is not used as an accessibility status.';


--
-- Name: venue_sport; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.venue_sport (
    venue_sport_id bigint NOT NULL,
    venue_id text NOT NULL,
    sport text NOT NULL,
    court_count integer,
    surface_type text
);


--
-- Name: COLUMN venue_sport.surface_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_sport.surface_type IS 'Surface description from the source. It is not treated as an accessibility value.';


--
-- Name: sport_vocabulary; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.sport_vocabulary AS
 SELECT vs.sport,
    count(DISTINCT vs.venue_id) AS venue_count
   FROM (public.venue_sport vs
     JOIN public.venue v ON ((v.venue_id = vs.venue_id)))
  WHERE (vs.sport IS NOT NULL)
  GROUP BY vs.sport
  WITH NO DATA;


--
-- Name: MATERIALIZED VIEW sport_vocabulary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON MATERIALIZED VIEW public.sport_vocabulary IS 'Distinct sports present in loaded venues, with the number of venues offering each. Backs the sport typeahead; a sport absent from this list has no venues and must not be offered.';


--
-- Name: venue_access_chain; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.venue_access_chain (
    venue_id text NOT NULL,
    link public.access_link NOT NULL,
    status public.publication_status NOT NULL,
    basis public.status_basis NOT NULL,
    detail text,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    kind public.amenity_kind
);


--
-- Name: TABLE venue_access_chain; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.venue_access_chain IS 'The access chain for each venue. Four links carry a kind and are rendered as facility tiles; enter and play carry no kind and are always no_published_information.';


--
-- Name: COLUMN venue_access_chain.kind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_access_chain.kind IS 'The facility tile this link is rendered as. NULL for enter and play, which no registered dataset publishes and which appear only in the limits section of the venue card.';


--
-- Name: venue_amenity_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.venue_amenity_status (
    venue_id text NOT NULL,
    kind public.amenity_kind NOT NULL,
    load_run_id bigint NOT NULL,
    status public.publication_status NOT NULL,
    basis public.status_basis NOT NULL,
    nearest_amenity_id text,
    distance_m numeric(10,1),
    within_250m boolean DEFAULT false NOT NULL,
    within_500m boolean DEFAULT false NOT NULL,
    within_1000m boolean DEFAULT false NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    source_id text,
    alternative_amenity_id text,
    alternative_distance_m numeric(10,1),
    detail_amenity_id text,
    detail_source_id text,
    detail_distance_m numeric(10,1),
    CONSTRAINT alternative_distance_paired CHECK (((alternative_amenity_id IS NULL) = (alternative_distance_m IS NULL))),
    CONSTRAINT alternative_only_when_unavailable CHECK (((alternative_amenity_id IS NULL) OR (status = 'not_available'::public.publication_status))),
    CONSTRAINT bands_match_distance CHECK (((within_250m = ((distance_m IS NOT NULL) AND (distance_m <= (250)::numeric))) AND (within_500m = ((distance_m IS NOT NULL) AND (distance_m <= (500)::numeric))) AND (within_1000m = ((distance_m IS NOT NULL) AND (distance_m <= (1000)::numeric))))),
    CONSTRAINT confirmed_has_evidence CHECK (((status <> 'confirmed'::public.publication_status) OR (basis = 'publisher_attribute'::public.status_basis) OR ((nearest_amenity_id IS NOT NULL) AND (distance_m IS NOT NULL)))),
    CONSTRAINT detail_distance_paired CHECK (((detail_amenity_id IS NULL) = (detail_distance_m IS NULL))),
    CONSTRAINT detail_only_on_publisher_confirmed CHECK (((detail_amenity_id IS NULL) OR ((status = 'confirmed'::public.publication_status) AND (basis = 'publisher_attribute'::public.status_basis))))
);


--
-- Name: COLUMN venue_amenity_status.distance_m; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_amenity_status.distance_m IS 'Straight-line distance in metres. This is not walking distance.';


--
-- Name: COLUMN venue_amenity_status.source_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_amenity_status.source_id IS 'The source that produced this status: the venue source when the basis is publisher_attribute, the amenity source when it is spatial_proximity, NULL when nothing published it.';


--
-- Name: COLUMN venue_amenity_status.alternative_amenity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_amenity_status.alternative_amenity_id IS 'Set only where status is not_available and a public facility of the same kind was found within the search radius. The venue has none; this one is nearby. Null in every other case, including confirmed, because there the nearest facility is already the answer rather than an alternative to it.';


--
-- Name: COLUMN venue_amenity_status.alternative_distance_m; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_amenity_status.alternative_distance_m IS 'Straight-line metres to alternative_amenity_id. Same measurement basis and same limitation as distance_m: a railway line between the two makes the real journey longer.';


--
-- Name: COLUMN venue_amenity_status.detail_amenity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_amenity_status.detail_amenity_id IS 'A separately published description of the same facility, attached to a status that was already confirmed by the venue publisher. Never the reason the status is confirmed.';


--
-- Name: COLUMN venue_amenity_status.detail_source_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.venue_amenity_status.detail_source_id IS 'Who published the detail, which is not who published the status. Both are shown on the card, because a 2026 confirmation described by a 2022 record is two facts with two dates and collapsing them into one would misstate both.';


--
-- Name: CONSTRAINT bands_match_distance ON venue_amenity_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON CONSTRAINT bands_match_distance ON public.venue_amenity_status IS 'Makes sure the distance bands match the stored distance.';


--
-- Name: venue_card; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.venue_card AS
 SELECT v.venue_id,
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
    COALESCE(s.sports, ARRAY[]::text[]) AS sports,
    COALESCE(s.surface_types, ARRAY[]::text[]) AS surface_types,
    (t.status)::text AS toilet_status,
    (t.basis)::text AS toilet_basis,
    t.distance_m AS toilet_distance_m,
    t.within_250m AS toilet_within_250m,
    t.within_500m AS toilet_within_500m,
    t.within_1000m AS toilet_within_1000m,
    t.source_id AS toilet_source_id,
    at.name AS toilet_amenity_name,
    at.is_inside_venue AS toilet_is_inside_venue,
    at.opening_hours AS toilet_opening_hours,
    at.key_required AS toilet_key_required,
    at.mlak_24h AS toilet_mlak_24h,
    at.payment_required AS toilet_payment_required,
    at.access_note AS toilet_access_note,
    (p.status)::text AS parking_status,
    (p.basis)::text AS parking_basis,
    p.distance_m AS parking_distance_m,
    p.within_250m AS parking_within_250m,
    p.within_500m AS parking_within_500m,
    p.within_1000m AS parking_within_1000m,
    p.source_id AS parking_source_id,
    ap.name AS parking_amenity_name,
    ap.is_inside_venue AS parking_is_inside_venue,
    (r.status)::text AS transport_status,
    (r.basis)::text AS transport_basis,
    r.distance_m AS transport_distance_m,
    r.within_250m AS transport_within_250m,
    r.within_500m AS transport_within_500m,
    r.within_1000m AS transport_within_1000m,
    r.source_id AS transport_source_id,
    ar.name AS transport_amenity_name,
    ar.transport_mode,
    (c.status)::text AS change_status,
    (c.basis)::text AS change_basis,
    c.distance_m AS change_distance_m,
    c.within_250m AS change_within_250m,
    c.within_500m AS change_within_500m,
    c.within_1000m AS change_within_1000m,
    c.source_id AS change_source_id,
    ac.name AS change_amenity_name,
    ac.is_inside_venue AS change_is_inside_venue,
    ac.changing_places AS change_is_changing_places,
    ac.has_shower AS change_has_shower,
    ac.opening_hours AS change_opening_hours
   FROM (((((((((public.venue v
     LEFT JOIN LATERAL ( SELECT array_remove(array_agg(DISTINCT vs.sport), NULL::text) AS sports,
            array_remove(array_agg(DISTINCT vs.surface_type), NULL::text) AS surface_types
           FROM public.venue_sport vs
          WHERE (vs.venue_id = v.venue_id)) s ON (true))
     LEFT JOIN public.venue_amenity_status t ON (((t.venue_id = v.venue_id) AND (t.kind = 'accessible_toilet'::public.amenity_kind))))
     LEFT JOIN public.amenity at ON ((at.amenity_id = t.nearest_amenity_id)))
     LEFT JOIN public.venue_amenity_status p ON (((p.venue_id = v.venue_id) AND (p.kind = 'accessible_parking'::public.amenity_kind))))
     LEFT JOIN public.amenity ap ON ((ap.amenity_id = p.nearest_amenity_id)))
     LEFT JOIN public.venue_amenity_status r ON (((r.venue_id = v.venue_id) AND (r.kind = 'accessible_transport_stop'::public.amenity_kind))))
     LEFT JOIN public.amenity ar ON ((ar.amenity_id = r.nearest_amenity_id)))
     LEFT JOIN public.venue_amenity_status c ON (((c.venue_id = v.venue_id) AND (c.kind = 'accessible_change_facility'::public.amenity_kind))))
     LEFT JOIN public.amenity ac ON ((ac.amenity_id = c.nearest_amenity_id)))
  WITH NO DATA;


--
-- Name: MATERIALIZED VIEW venue_card; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON MATERIALIZED VIEW public.venue_card IS 'The read model for venue search and the venue card. Refreshed by the pipeline, never computed at request time. A status column is the status at the 1 km ceiling; the API applies the user distance limit using the within_250m, within_500m and within_1000m flags rather than reading status directly.';


--
-- Name: venue_facility_detail; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.venue_facility_detail AS
 SELECT s.venue_id,
    (s.kind)::text AS kind,
    (s.status)::text AS status,
    (s.basis)::text AS basis,
    s.distance_m,
    s.within_250m,
    s.within_500m,
    s.within_1000m,
    s.source_id,
    src.name AS source_name,
    src.attribution_text,
    src.publisher_last_updated AS source_last_updated,
    a.amenity_id,
    a.name AS amenity_name,
    a.address AS amenity_address,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN 'at the venue'::text
            WHEN a.is_inside_venue THEN 'at the venue'::text
            WHEN (a.amenity_id IS NOT NULL) THEN 'a separate public facility nearby'::text
            ELSE 'no source records whether this is inside the venue or nearby'::text
        END AS location_relative_to_venue,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.opening_hours
            ELSE a.opening_hours
        END AS opening_hours,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.key_required
            ELSE a.key_required
        END AS key_required,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.mlak_24h
            ELSE a.mlak_24h
        END AS mlak_24h,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.payment_required
            ELSE a.payment_required
        END AS payment_required,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.access_note
            ELSE a.access_note
        END AS access_note,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.changing_places
            ELSE a.changing_places
        END AS changing_places,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.has_shower
            ELSE a.has_shower
        END AS has_shower,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.ambulant
            ELSE a.ambulant
        END AS ambulant,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.left_hand_transfer
            ELSE a.left_hand_transfer
        END AS left_hand_transfer,
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.right_hand_transfer
            ELSE a.right_hand_transfer
        END AS right_hand_transfer,
    ((s.status = 'confirmed'::public.publication_status) AND (
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.opening_hours
            ELSE a.opening_hours
        END IS NULL)) AS opening_hours_unrecorded,
    ((s.status = 'confirmed'::public.publication_status) AND (
        CASE
            WHEN (s.basis = 'publisher_attribute'::public.status_basis) THEN d.key_required
            ELSE a.key_required
        END IS NULL)) AS key_requirement_unrecorded,
    a.facility_note,
    a.transport_mode,
    a.wheelchair_boarding,
    d.amenity_id AS detail_amenity_id,
    s.detail_source_id,
    dsrc.name AS detail_source_name,
    dsrc.publisher_last_updated AS detail_source_last_updated,
    s.detail_distance_m,
    (d.amenity_id IS NOT NULL) AS detail_is_attached,
    alt.amenity_id AS alternative_amenity_id,
    alt.name AS alternative_name,
    s.alternative_distance_m,
    altsrc.name AS alternative_source_name,
    altsrc.publisher_last_updated AS alternative_source_last_updated,
    alt.opening_hours AS alternative_opening_hours,
    alt.key_required AS alternative_key_required,
    (alt.amenity_id IS NOT NULL) AS has_nearby_alternative
   FROM ((((((public.venue_amenity_status s
     LEFT JOIN public.amenity a ON ((a.amenity_id = s.nearest_amenity_id)))
     LEFT JOIN public.amenity d ON ((d.amenity_id = s.detail_amenity_id)))
     LEFT JOIN public.amenity alt ON ((alt.amenity_id = s.alternative_amenity_id)))
     LEFT JOIN public.source src ON ((src.source_id = s.source_id)))
     LEFT JOIN public.source dsrc ON ((dsrc.source_id = s.detail_source_id)))
     LEFT JOIN public.source altsrc ON ((altsrc.source_id = alt.source_id)));


--
-- Name: VIEW venue_facility_detail; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.venue_facility_detail IS 'One row per venue per facility tile. Carries the source name and date required by AC1.3.2, the inside-or-nearby statement required by AC2.1.3, the explicit unrecorded flags required by AC2.1.4, and from migration 007 both the attached detail for an on-site confirmation and the nearby alternative to a published absence. detail_source_name is deliberately separate from source_name: the status and its description can come from different publishers with different dates.';


--
-- Name: venue_sport_venue_sport_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.venue_sport_venue_sport_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: venue_sport_venue_sport_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.venue_sport_venue_sport_id_seq OWNED BY public.venue_sport.venue_sport_id;


--
-- Name: load_run load_run_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_run ALTER COLUMN load_run_id SET DEFAULT nextval('public.load_run_load_run_id_seq'::regclass);


--
-- Name: quarantine quarantine_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quarantine ALTER COLUMN quarantine_id SET DEFAULT nextval('public.quarantine_quarantine_id_seq'::regclass);


--
-- Name: venue_sport venue_sport_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_sport ALTER COLUMN venue_sport_id SET DEFAULT nextval('public.venue_sport_venue_sport_id_seq'::regclass);


--
-- Name: amenity amenity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.amenity
    ADD CONSTRAINT amenity_pkey PRIMARY KEY (amenity_id);


--
-- Name: lga lga_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lga
    ADD CONSTRAINT lga_pkey PRIMARY KEY (lga_code);


--
-- Name: load_run load_run_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_run
    ADD CONSTRAINT load_run_pkey PRIMARY KEY (load_run_id);


--
-- Name: postal_area postal_area_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.postal_area
    ADD CONSTRAINT postal_area_pkey PRIMARY KEY (poa_code);


--
-- Name: quarantine quarantine_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quarantine
    ADD CONSTRAINT quarantine_pkey PRIMARY KEY (quarantine_id);


--
-- Name: source source_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source
    ADD CONSTRAINT source_pkey PRIMARY KEY (source_id);


--
-- Name: suburb suburb_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.suburb
    ADD CONSTRAINT suburb_pkey PRIMARY KEY (suburb_code);


--
-- Name: venue_access_chain venue_access_chain_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_access_chain
    ADD CONSTRAINT venue_access_chain_pkey PRIMARY KEY (venue_id, link);


--
-- Name: venue_amenity_status venue_amenity_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_pkey PRIMARY KEY (venue_id, kind);


--
-- Name: venue venue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue
    ADD CONSTRAINT venue_pkey PRIMARY KEY (venue_id);


--
-- Name: venue_sport venue_sport_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_sport
    ADD CONSTRAINT venue_sport_pkey PRIMARY KEY (venue_sport_id);


--
-- Name: venue_sport venue_sport_venue_id_sport_surface_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_sport
    ADD CONSTRAINT venue_sport_venue_id_sport_surface_type_key UNIQUE (venue_id, sport, surface_type);


--
-- Name: amenity_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX amenity_geom_idx ON public.amenity USING gist (geom);


--
-- Name: amenity_kind_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX amenity_kind_geom_idx ON public.amenity USING gist (geom) INCLUDE (kind);


--
-- Name: amenity_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX amenity_kind_idx ON public.amenity USING btree (kind);


--
-- Name: lga_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX lga_geom_idx ON public.lga USING gist (geom);


--
-- Name: lga_gm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX lga_gm_idx ON public.lga USING btree (in_greater_melbourne) WHERE in_greater_melbourne;


--
-- Name: load_run_source_dt_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX load_run_source_dt_idx ON public.load_run USING btree (source_id, dt_partition DESC);


--
-- Name: postal_area_code_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX postal_area_code_idx ON public.postal_area USING btree (poa_code);


--
-- Name: postal_area_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX postal_area_geom_idx ON public.postal_area USING gist (geom);


--
-- Name: quarantine_run_reason_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quarantine_run_reason_idx ON public.quarantine USING btree (load_run_id, reason);


--
-- Name: search_location_gm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_location_gm_idx ON public.search_location USING btree (in_greater_melbourne) WHERE in_greater_melbourne;


--
-- Name: search_location_label_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_location_label_trgm_idx ON public.search_location USING gin (lower(label) public.gin_trgm_ops);


--
-- Name: search_location_pk_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX search_location_pk_idx ON public.search_location USING btree (location_kind, code);


--
-- Name: search_location_point_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX search_location_point_idx ON public.search_location USING gist (search_point);


--
-- Name: sport_vocabulary_pk_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX sport_vocabulary_pk_idx ON public.sport_vocabulary USING btree (sport);


--
-- Name: sport_vocabulary_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sport_vocabulary_trgm_idx ON public.sport_vocabulary USING gin (lower(sport) public.gin_trgm_ops);


--
-- Name: suburb_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX suburb_geom_idx ON public.suburb USING gist (geom);


--
-- Name: suburb_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX suburb_name_idx ON public.suburb USING btree (lower(suburb_name));


--
-- Name: vac_link_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vac_link_status_idx ON public.venue_access_chain USING btree (link, status);


--
-- Name: vas_kind_1000_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vas_kind_1000_idx ON public.venue_amenity_status USING btree (kind) WHERE within_1000m;


--
-- Name: vas_kind_250_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vas_kind_250_idx ON public.venue_amenity_status USING btree (kind) WHERE within_250m;


--
-- Name: vas_kind_500_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vas_kind_500_idx ON public.venue_amenity_status USING btree (kind) WHERE within_500m;


--
-- Name: vas_venue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vas_venue_idx ON public.venue_amenity_status USING btree (venue_id);


--
-- Name: venue_card_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_card_geom_idx ON public.venue_card USING gist (geom);


--
-- Name: venue_card_lga_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_card_lga_idx ON public.venue_card USING btree (lga_code);


--
-- Name: venue_card_pk_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX venue_card_pk_idx ON public.venue_card USING btree (venue_id);


--
-- Name: venue_card_postcode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_card_postcode_idx ON public.venue_card USING btree (postcode);


--
-- Name: venue_card_sports_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_card_sports_idx ON public.venue_card USING gin (sports);


--
-- Name: venue_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_geom_idx ON public.venue USING gist (geom);


--
-- Name: venue_lga_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_lga_idx ON public.venue USING btree (lga_code);


--
-- Name: venue_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_name_idx ON public.venue USING gin (to_tsvector('english'::regconfig, name));


--
-- Name: venue_postcode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_postcode_idx ON public.venue USING btree (postcode);


--
-- Name: venue_sport_sport_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_sport_sport_idx ON public.venue_sport USING btree (lower(sport));


--
-- Name: venue_sport_venue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX venue_sport_venue_idx ON public.venue_sport USING btree (venue_id);


--
-- Name: amenity amenity_load_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.amenity
    ADD CONSTRAINT amenity_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);


--
-- Name: amenity amenity_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.amenity
    ADD CONSTRAINT amenity_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: lga lga_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lga
    ADD CONSTRAINT lga_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: load_run load_run_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_run
    ADD CONSTRAINT load_run_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: postal_area postal_area_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.postal_area
    ADD CONSTRAINT postal_area_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: quarantine quarantine_load_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quarantine
    ADD CONSTRAINT quarantine_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);


--
-- Name: quarantine quarantine_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quarantine
    ADD CONSTRAINT quarantine_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: suburb suburb_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.suburb
    ADD CONSTRAINT suburb_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: venue_access_chain venue_access_chain_venue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_access_chain
    ADD CONSTRAINT venue_access_chain_venue_id_fkey FOREIGN KEY (venue_id) REFERENCES public.venue(venue_id) ON DELETE CASCADE;


--
-- Name: venue_amenity_status venue_amenity_status_alternative_amenity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_alternative_amenity_id_fkey FOREIGN KEY (alternative_amenity_id) REFERENCES public.amenity(amenity_id);


--
-- Name: venue_amenity_status venue_amenity_status_detail_amenity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_detail_amenity_id_fkey FOREIGN KEY (detail_amenity_id) REFERENCES public.amenity(amenity_id);


--
-- Name: venue_amenity_status venue_amenity_status_detail_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_detail_source_id_fkey FOREIGN KEY (detail_source_id) REFERENCES public.source(source_id);


--
-- Name: venue_amenity_status venue_amenity_status_load_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);


--
-- Name: venue_amenity_status venue_amenity_status_nearest_amenity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_nearest_amenity_id_fkey FOREIGN KEY (nearest_amenity_id) REFERENCES public.amenity(amenity_id);


--
-- Name: venue_amenity_status venue_amenity_status_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: venue_amenity_status venue_amenity_status_venue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_amenity_status
    ADD CONSTRAINT venue_amenity_status_venue_id_fkey FOREIGN KEY (venue_id) REFERENCES public.venue(venue_id) ON DELETE CASCADE;


--
-- Name: venue venue_lga_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue
    ADD CONSTRAINT venue_lga_code_fkey FOREIGN KEY (lga_code) REFERENCES public.lga(lga_code);


--
-- Name: venue venue_load_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue
    ADD CONSTRAINT venue_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_run(load_run_id);


--
-- Name: venue venue_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue
    ADD CONSTRAINT venue_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);


--
-- Name: venue_sport venue_sport_venue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.venue_sport
    ADD CONSTRAINT venue_sport_venue_id_fkey FOREIGN KEY (venue_id) REFERENCES public.venue(venue_id) ON DELETE CASCADE;


--
--



--
-- Populate the materialised views.
--
-- pg_dump writes materialised views WITH NO DATA, so straight after this file
-- is applied every one of them raises
--
--   ERROR: materialized view "venue_card" has not been populated
--
-- on any read. The migrations do not behave this way, because CREATE
-- MATERIALIZED VIEW ... AS SELECT populates on creation and an empty view
-- returns zero rows rather than an error.
--
-- The first pipeline run refreshes all three anyway. This block exists so that
-- the window between applying the schema and running the pipeline is not a
-- window in which three API endpoints appear to be broken.
--
-- These are empty at this point. They stay empty until data is loaded and the
-- status builder has run. Empty is a valid state; unpopulated is not.
--

-- Schema-qualified because pg_dump sets an empty search_path at the head of
-- this file. An unqualified name does not resolve here.

REFRESH MATERIALIZED VIEW public.search_location;
REFRESH MATERIALIZED VIEW public.sport_vocabulary;
REFRESH MATERIALIZED VIEW public.venue_card;