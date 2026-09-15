-- ============================================================================
-- 011_vocabulary_and_summary.sql
--
-- Iteration 2, Epic 3. The map legend becomes data, and the Read Aloud summary
-- is given a stated home.
--
-- WHY A LEGEND NEEDS A TABLE AT ALL
--     Until now the legend lived in CSS (frontend/src/styles/main.css,
--     .map-legend). CSS can colour a marker but it cannot be asked what the
--     marker means, which makes three acceptance criteria unverifiable:
--
--       AC3.1.1  the legend explains every icon and colour used on the map.
--                A legend written by hand explains the icons somebody
--                remembered. A legend generated from the enum that produces
--                the markers explains all of them, including the one added
--                next semester.
--       AC3.1.2  every facility type carries a different shape, colour AND
--                text label. Three channels, so no one of them is load
--                bearing on its own.
--       AC3.1.4  a text version of the legend exists for screen readers. The
--                spoken wording is a column on the same row as the drawn
--                wording, so the two cannot drift apart. If they lived in
--                separate files, the day somebody renames a marker is the day
--                the screen reader starts describing a marker that no longer
--                exists, and nobody who can see the map would notice.
--
-- WHY SHAPE IS THE PRIMARY CHANNEL AND COLOUR IS REDUNDANT
--     AC3.1.3 requires the types to stay distinguishable in greyscale. Colour
--     alone fails that for anyone with a monochrome display, a printed page,
--     a low quality projector, or any of the several forms of colour vision
--     deficiency. So shape carries the meaning and colour repeats it: the four
--     shapes below are circle, square, triangle and diamond, which stay told
--     apart at small sizes and survive desaturation completely. The four
--     colours are additionally chosen so their relative luminances separate
--     under desaturation as well, which is belt and braces rather than the
--     mechanism.
--
--     colour_hex is the fill. Markers are drawn with a dark stroke, which is
--     what gives every marker contrast against a pale basemap; that frees the
--     fill to span the luminance range instead of huddling in the dark end.
--
-- WHY THE VIEW IS DRIVEN BY THE ENUM AND NOT BY THE LITERAL LIST
--     The FROM clause below unnests amenity_kind. The descriptive columns are
--     LEFT JOINed onto it. Add a value to amenity_kind without adding a row
--     here and the view gains a row whose label is NULL: the gap shows up as
--     data, loudly, on the first query. The alternative (a table listing the
--     four kinds) would simply lose the new kind in silence, which is the
--     exact failure AC3.1.1 exists to prevent.
--
-- REVERSIBILITY
--     Additive only. One view, no table, column, type or index is altered, so
--     the rollback is the DROP block at the foot of this file and nothing else.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. facility_legend
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW public.facility_legend AS
SELECT
    k.ordinal::integer                                  AS ordinal,
    k.kind::text                                        AS kind,
    v.display_label,
    v.shape,
    v.colour_token,
    v.colour_hex,
    v.description,
    v.screen_reader_text
FROM (
    -- WITH ORDINALITY preserves the order the enum was declared in, which is
    -- the order the four tiles already appear in everywhere else in the
    -- product. A legend in a different order from the tiles beside it is a
    -- legend people have to translate.
    SELECT e.kind, e.ord AS ordinal
      FROM unnest(enum_range(NULL::public.amenity_kind)) WITH ORDINALITY AS e(kind, ord)
) k
LEFT JOIN (
    VALUES
    (
        'accessible_toilet',
        'Accessible toilet',
        'circle',
        '--facility-toilet',
        '#0B3D66',
        'A toilet with wheelchair access, either at the venue or a separate public toilet nearby.',
        'Accessible toilet: a circle, dark blue.'
    ),
    (
        'accessible_parking',
        'Accessible parking',
        'square',
        '--facility-parking',
        '#B3541E',
        'An accessible parking bay, either at the venue or on a nearby street.',
        'Accessible parking: a square, burnt orange.'
    ),
    (
        'accessible_transport_stop',
        -- Labelled as what the data actually confirms. Only railway stations
        -- publish wheelchair_boarding, so calling this "accessible transport"
        -- would claim a bus network we have no record of.
        'Step-free railway station',
        'triangle',
        '--facility-transport',
        '#7A9E3F',
        'A railway station the operator records as step-free.',
        'Step-free railway station: a triangle, olive green.'
    ),
    (
        'accessible_change_facility',
        'Accessible change facility',
        'diamond',
        '--facility-change',
        '#F2C744',
        'An accessible change facility, which may or may not be an accredited Changing Places room.',
        'Accessible change facility: a diamond, gold.'
    )
) AS v (
    kind,
    display_label,
    shape,
    colour_token,
    colour_hex,
    description,
    screen_reader_text
) ON v.kind = k.kind::text
-- A view without an ORDER BY returns rows in whatever order the planner
-- likes, and the legend's order is part of its meaning: it is read down the
-- side of a map whose tiles are drawn in the same sequence.
ORDER BY k.ordinal;

COMMENT ON VIEW public.facility_legend IS
    'AC3.1.1, AC3.1.2 and AC3.1.4. One row per amenity_kind with the shape, colour and text label the map marker is drawn from, and the spoken wording a screen reader reads out. Driven by unnest(enum_range(amenity_kind)) so a marker type can never exist on the map without a legend entry: an unlabelled kind appears here as a row with a NULL display_label rather than quietly missing. Served by GET /api/v1/facility-types.';

COMMENT ON COLUMN public.facility_legend.shape IS
    'circle, square, triangle or diamond. THE PRIMARY CHANNEL. AC3.1.3 requires the types to be told apart in greyscale, so meaning is carried by shape and merely repeated by colour. Do not add a fifth kind that reuses an existing shape.';

COMMENT ON COLUMN public.facility_legend.colour_token IS
    'The CSS custom property the frontend defines for this type. A token rather than a literal so a theme can restyle the map without editing the database, and so the legend swatch and the marker cannot be given two different colours.';

COMMENT ON COLUMN public.facility_legend.colour_hex IS
    'The fill the token resolves to by default. Present so the greyscale requirement is checkable rather than asserted: the four values have relative luminances of roughly 0.04, 0.16, 0.29 and 0.60, which stay apart after desaturation. Markers carry a dark stroke, which is where their contrast against a pale basemap comes from.';

COMMENT ON COLUMN public.facility_legend.screen_reader_text IS
    'AC3.1.4. The spoken form of this legend entry, on the SAME ROW as the drawn one. Keeping them together is the point: a spoken legend maintained in a separate file drifts from the visual one and nobody who can see the map finds out.';


-- ---------------------------------------------------------------------------
-- 2. The Read Aloud summary — deliberately not stored here
-- ---------------------------------------------------------------------------
--
-- AC3.3.1 wants Read Aloud to speak a short summary of a page rather than the
-- whole page, and AC3.3.3 wants the sentence being spoken highlighted. That
-- summary is assembled in the API layer (app/domain/summary.py) and served as
-- summary_sentences, an ordered array of one complete sentence per element.
--
-- It is NOT a column on venue_card or on program, and that is a decision
-- rather than an omission:
--
--   * The four facility sentences state each status AT THE DISTANCE BAND THE
--     REQUEST ASKED FOR. "Nearest accessible toilet 640 m away, beyond your
--     250 m limit" and "public accessible toilet 640 m away" are the same row
--     read at two different bands. A stored sentence would have to pick one
--     band and would then be wrong for every other, which is worse than no
--     sentence at all when the subject is accessibility.
--
--   * The summary must say exactly what the page says. Built from the same
--     response object the page renders, it cannot disagree with it. Built
--     here, it would be a second rendering of the same facts, maintained by
--     different people, and the two would part company.
--
-- Nothing in the serving store needs to change for Read Aloud. This note
-- exists so the next person to look for a summary_sentences column knows it
-- was considered and why it is not here.

COMMIT;


-- ============================================================================
-- ROLLBACK
--
--   BEGIN;
--   DROP VIEW IF EXISTS public.facility_legend;
--   COMMIT;
-- ============================================================================
