-- Seed for the crosswalk verification. Small on purpose: one programme per
-- crosswalk behaviour that changed.
BEGIN;

INSERT INTO source (source_id, name, publisher, licence_name, licence_url,
                    attribution_text, publisher_scope)
VALUES ('DS-01', 'Facilities', 'DJSIR', 'CC BY', 'http://x', 'attrib', 'statewide'),
       ('DS-09', 'AAA Play', 'AAA', 'CC BY', 'http://x', 'attrib', 'statewide');

INSERT INTO load_run (load_run_id, dt_partition, source_id, raw_object_key, raw_sha256, outcome)
VALUES (1, '2026-09-16', 'DS-01', 'k',
        '0000000000000000000000000000000000000000000000000000000000000000', 'succeeded'),
       (2, '2026-09-16', 'DS-09', 'k',
        '1111111111111111111111111111111111111111111111111111111111111111', 'succeeded');

-- Venues, so sport_vocabulary holds the names the crosswalk points at.
INSERT INTO venue (venue_id, source_id, load_run_id, name, geom,
                   onsite_accessible_toilet, onsite_accessible_parking, retrieved_at)
VALUES ('V1', 'DS-01', 1, 'Aquatic Centre',
        ST_SetSRID(ST_MakePoint(144.96, -37.81), 7844),
        'confirmed', 'confirmed', now()),
       ('V2', 'DS-01', 1, 'Tennis Centre',
        ST_SetSRID(ST_MakePoint(144.97, -37.82), 7844),
        'confirmed', 'confirmed', now());

INSERT INTO venue_sport (venue_id, sport) VALUES
    ('V1', 'Swimming'),
    ('V2', 'Tennis (Outdoor)'),
    ('V2', 'Tennis (Indoor)'),
    ('V1', 'Basketball');

REFRESH MATERIALIZED VIEW sport_vocabulary;

-- Programmes: one per case the crosswalk decides differently from a plain
-- label match.
INSERT INTO program (program_id, source_id, load_run_id, publisher_key, kind, name,
                     geom, retrieved_at)
VALUES ('P-AQUA',   'DS-09', 2, 1, 'program', 'Aqua aerobics for beginners',
        ST_SetSRID(ST_MakePoint(144.96, -37.81), 7844), now()),
       ('P-TENNIS', 'DS-09', 2, 2, 'program', 'Wheelchair tennis social',
        ST_SetSRID(ST_MakePoint(144.97, -37.82), 7844), now()),
       ('P-BOCCIA', 'DS-09', 2, 3, 'program', 'Boccia club',
        ST_SetSRID(ST_MakePoint(144.95, -37.80), 7844), now()),
       ('P-ART',    'DS-09', 2, 4, 'program', 'Art group',
        ST_SetSRID(ST_MakePoint(144.95, -37.80), 7844), now()),
       ('P-NEW',    'DS-09', 2, 5, 'program', 'Brand new activity',
        ST_SetSRID(ST_MakePoint(144.95, -37.80), 7844), now());

INSERT INTO program_sport (program_id, sport_key, sport_label, source_id, load_run_id)
VALUES ('P-AQUA',   'aqua_aerobics', 'Aqua aerobics', 'DS-09', 2),
       ('P-TENNIS', 'tennis',        'Tennis',        'DS-09', 2),
       ('P-BOCCIA', 'boccia',        'Boccia',        'DS-09', 2),
       ('P-ART',    'art',           'Art',           'DS-09', 2),
       -- No crosswalk row: an unreviewed term, the case the LEFT JOIN exists for.
       ('P-NEW',    'quidditch',     'Quidditch',     'DS-09', 2);

COMMIT;
