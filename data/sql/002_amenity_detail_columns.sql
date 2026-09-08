-- sql/002_amenity_detail_columns.sql
--
-- Adds the extra amenity fields from DS-02.
-- 001 has already been applied, so these changes are added as a new migration.

ALTER TABLE amenity
    -- Details for change facilities
    ADD COLUMN changing_places boolean,

    ADD COLUMN byo_sling boolean,

    ADD COLUMN has_shower boolean,

    -- Toilet accessibility details
    ADD COLUMN ambulant boolean,

    ADD COLUMN left_hand_transfer boolean,
    ADD COLUMN right_hand_transfer boolean,

    -- Parking recorded by the toilet dataset
    ADD COLUMN accessible_parking_on_site boolean,

    -- Address from the source data
    ADD COLUMN address text;


COMMENT ON COLUMN amenity.changing_places IS
    'True when the source records a Changing Places facility, false for a general adult change facility, and null when the amenity is not a change facility.';

COMMENT ON COLUMN amenity.left_hand_transfer IS
    'Indicates whether a left-hand transfer is available.';

COMMENT ON COLUMN amenity.accessible_parking_on_site IS
    'Accessible parking recorded at the toilet facility. This is separate from the accessible_parking amenity type.';