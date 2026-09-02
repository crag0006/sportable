-- sql/007_detail_attachment.sql
--
-- Two changes, both about showing the person more of what has already been
-- published, and neither of them changing a single status.
--
--
-- CHANGE 1. A published "no" now carries the nearby alternative with it.
--
-- 574 of 2,160 venues publish that they have no accessible toilet. Today the
-- tile reads not_available and stops there, even though the status row already
-- holds the nearest public toilet and its distance. The person standing to
-- benefit most from "there is one 130 m away" is precisely the person at a
-- venue that has none.
--
-- The status does not move. not_available stays not_available, because the
-- venue's own record said so and a public toilet down the road does not make
-- the venue's toilet exist. What changes is that the alternative stops being
-- invisible.
--
--
-- CHANGE 2. A bare yes gains the detail somebody else published.
--
-- When DS-01 says a venue has an accessible toilet, that is a yes and nothing
-- more: no opening hours, no key requirement, no transfer side. DS-02 records
-- all of those, for 3,475 Victorian accessible toilets.
--
-- Where a venue confirms an on-site accessible toilet AND a DS-02 accessible
-- toilet sits within DETAIL_ATTACH_M of it, that DS-02 record is almost
-- certainly describing the venue's own toilet, and its detail is attached to
-- the venue's confirmed status.
--
-- The line this does not cross: the STATUS still comes from DS-01 and only from
-- DS-01. The DETAIL comes from DS-02 and is attributed to DS-02 separately.
-- Proximity is never allowed to create a confirmed here; it only decides which
-- published description to attach to a confirmed that already existed. If the
-- attachment is wrong, a person sees the wrong opening hours for a toilet that
-- is genuinely there, which is a different and much smaller failure than being
-- told a toilet exists when it does not.
--
-- The 50 m threshold is a choice, not a published fact, and belongs in the
-- limitation register as one.


BEGIN;


-- Change 1

ALTER TABLE venue_amenity_status
    ADD COLUMN alternative_amenity_id text REFERENCES amenity(amenity_id),
    ADD COLUMN alternative_distance_m numeric(10, 1);

COMMENT ON COLUMN venue_amenity_status.alternative_amenity_id IS
    'Set only where status is not_available and a public facility of the same kind was found within the search radius. The venue has none; this one is nearby. Null in every other case, including confirmed, because there the nearest facility is already the answer rather than an alternative to it.';

COMMENT ON COLUMN venue_amenity_status.alternative_distance_m IS
    'Straight-line metres to alternative_amenity_id. Same measurement basis and same limitation as distance_m: a railway line between the two makes the real journey longer.';

ALTER TABLE venue_amenity_status
    ADD CONSTRAINT alternative_only_when_unavailable
    CHECK (
        alternative_amenity_id IS NULL
        OR status = 'not_available'
    );

ALTER TABLE venue_amenity_status
    ADD CONSTRAINT alternative_distance_paired
    CHECK (
        (alternative_amenity_id IS NULL) = (alternative_distance_m IS NULL)
    );


-- Change 2

ALTER TABLE venue_amenity_status
    ADD COLUMN detail_amenity_id text REFERENCES amenity(amenity_id),
    ADD COLUMN detail_source_id text REFERENCES source(source_id),
    ADD COLUMN detail_distance_m numeric(10, 1);

COMMENT ON COLUMN venue_amenity_status.detail_amenity_id IS
    'A separately published description of the same facility, attached to a status that was already confirmed by the venue publisher. Never the reason the status is confirmed.';

COMMENT ON COLUMN venue_amenity_status.detail_source_id IS
    'Who published the detail, which is not who published the status. Both are shown on the card, because a 2026 confirmation described by a 2022 record is two facts with two dates and collapsing them into one would misstate both.';

ALTER TABLE venue_amenity_status
    ADD CONSTRAINT detail_only_on_publisher_confirmed
    CHECK (
        detail_amenity_id IS NULL
        OR (status = 'confirmed' AND basis = 'publisher_attribute')
    );

ALTER TABLE venue_amenity_status
    ADD CONSTRAINT detail_distance_paired
    CHECK (
        (detail_amenity_id IS NULL) = (detail_distance_m IS NULL)
    );


-- The read model

DROP VIEW IF EXISTS venue_facility_detail;

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

    CASE
        WHEN s.basis = 'publisher_attribute'  THEN 'at the venue'
        WHEN a.is_inside_venue                THEN 'at the venue'
        WHEN a.amenity_id IS NOT NULL         THEN 'a separate public facility nearby'
        ELSE 'no source records whether this is inside the venue or nearby'
    END                                                 AS location_relative_to_venue,

    -- Detail.
    --
    -- Which amenity is allowed to describe this status depends on the basis,
    -- and getting this wrong is subtle. When basis is spatial_proximity the
    -- nearby amenity IS the answer, so its detail is the status's detail. When
    -- basis is publisher_attribute the venue answered for itself, and the
    -- nearest amenity may be a completely unrelated facility hundreds of
    -- metres away that happened to be closest. Its opening hours describe that
    -- other facility, not this venue's.
    --
    -- So on a publisher_attribute status, detail comes only from the amenity
    -- explicitly attached by the status builder within DETAIL_ATTACH_M, and
    -- from nowhere else. Without this the card shows a venue's confirmed
    -- toilet with the opening hours of a public toilet 599 m down the road.
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.opening_hours ELSE a.opening_hours END      AS opening_hours,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.key_required ELSE a.key_required END        AS key_required,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.mlak_24h ELSE a.mlak_24h END                AS mlak_24h,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.payment_required ELSE a.payment_required END AS payment_required,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.access_note ELSE a.access_note END          AS access_note,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.changing_places ELSE a.changing_places END   AS changing_places,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.has_shower ELSE a.has_shower END            AS has_shower,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.ambulant ELSE a.ambulant END                AS ambulant,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.left_hand_transfer ELSE a.left_hand_transfer END   AS left_hand_transfer,
    CASE WHEN s.basis = 'publisher_attribute'
         THEN d.right_hand_transfer ELSE a.right_hand_transfer END AS right_hand_transfer,

    -- AC2.1.4. True where the facility is real but nobody published the
    -- attribute, which the card must state in words rather than leave blank.
    -- A confirmed with no describing record at all is exactly that case.
    (s.status = 'confirmed'
        AND CASE WHEN s.basis = 'publisher_attribute'
                 THEN d.opening_hours ELSE a.opening_hours END IS NULL)  AS opening_hours_unrecorded,
    (s.status = 'confirmed'
        AND CASE WHEN s.basis = 'publisher_attribute'
                 THEN d.key_required ELSE a.key_required END IS NULL)    AS key_requirement_unrecorded,

    a.facility_note,
    a.transport_mode,
    a.wheelchair_boarding,

    -- Where the detail came from, when it is not the status source.
    d.amenity_id                                        AS detail_amenity_id,
    s.detail_source_id,
    dsrc.name                                           AS detail_source_name,
    dsrc.publisher_last_updated                         AS detail_source_last_updated,
    s.detail_distance_m,
    (d.amenity_id IS NOT NULL)                          AS detail_is_attached,

    -- The nearby alternative to a published absence.
    alt.amenity_id                                      AS alternative_amenity_id,
    alt.name                                            AS alternative_name,
    s.alternative_distance_m,
    altsrc.name                                         AS alternative_source_name,
    altsrc.publisher_last_updated                       AS alternative_source_last_updated,
    alt.opening_hours                                   AS alternative_opening_hours,
    alt.key_required                                    AS alternative_key_required,
    (alt.amenity_id IS NOT NULL)                        AS has_nearby_alternative

FROM venue_amenity_status s
LEFT JOIN amenity a    ON a.amenity_id   = s.nearest_amenity_id
LEFT JOIN amenity d    ON d.amenity_id   = s.detail_amenity_id
LEFT JOIN amenity alt  ON alt.amenity_id = s.alternative_amenity_id
LEFT JOIN source  src   ON src.source_id    = s.source_id
LEFT JOIN source  dsrc  ON dsrc.source_id   = s.detail_source_id
LEFT JOIN source  altsrc ON altsrc.source_id = alt.source_id;

COMMENT ON VIEW venue_facility_detail IS
    'One row per venue per facility tile. Carries the source name and date required by AC1.3.2, the inside-or-nearby statement required by AC2.1.3, the explicit unrecorded flags required by AC2.1.4, and from migration 007 both the attached detail for an on-site confirmation and the nearby alternative to a published absence. detail_source_name is deliberately separate from source_name: the status and its description can come from different publishers with different dates.';


COMMIT;
