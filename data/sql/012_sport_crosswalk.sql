-- ============================================================================
-- 012_sport_crosswalk.sql
--
-- Iteration 2, Epic 4, D6. Turns the publisher's sport terms into the sports a
-- venue search recognises, without losing the ones that have no venue sport.
--
-- WHY A TABLE AND NOT A CASE EXPRESSION
--     program_sport.sport_key holds AAA Play's own activity_type term, one of
--     82. venue_sport.sport holds the DS-01 register's wording, one of 80. The
--     two vocabularies were written by different people for different purposes
--     and agree on 47 terms out of 82. The other 35 need a decision each, and a
--     decision that lives in a WHERE clause is a decision nobody reviews.
--
--     The rows below are generated from data/ingestion/crosswalks/
--     ds09_sport_vocabulary.yaml, which is the reviewed artefact: it carries the
--     reasoning for every row, and a test in data/tests compares the two so they
--     cannot drift apart. EDIT THE YAML FIRST, then regenerate this block.
--
-- WHY IT IS MANY-TO-MANY
--     Two things a one-to-one alias map cannot say, and both are live:
--
--       'Bike riding, BMX & cycling' is ONE publisher term naming TWO vocabulary
--       sports. The backend's SPORT_ALIASES dict reaches Cycling and silently
--       misses BMX.
--
--       'Tennis' is one publisher term and the venue vocabulary has no
--       unqualified tennis entry at all, only 'Tennis (Outdoor)' and 'Tennis
--       (Indoor)'. Choosing one hides every venue of the other kind.
--
--     program_sport is keyed (program_id, sport_key), so a programme already
--     carries as many publisher terms as it likes — 52 of the 532 activities
--     carry more than one. This table adds the second half of the link, so a
--     search for EITHER sport finds the programme.
--
-- THE JUDGEMENT CALL THIS MIGRATION RECORDS
--     ADAPTIVE AND PARA SPORTS ARE NOT FOLDED INTO THEIR NON-ADAPTIVE PARENTS.
--     Boccia is not Bowls and is not Bocce. Adaptive climbing is not Bouldering.
--     Walking and rolling is not walking; the word "rolling" is the wheelchair
--     and it is the whole point of the term. Goalball and floor curling have no
--     parent in the venue register at all. Five terms carry relation
--     'added_adaptive', each maps only to itself, and a CHECK constraint below
--     enforces that rather than trusting it. On a product built for wheelchair
--     users, collapsing an adaptive sport into the sport it was adapted from
--     deletes the reason the programme exists.
--
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
--     It does not touch program_sport, venue_sport or the sport_vocabulary
--     materialised view. sport_vocabulary stays what it is — the sports of
--     venues actually loaded, so the venue typeahead never offers a sport with
--     no venues. The 20 sports this crosswalk adds are programme sports; they
--     reach the events sport list through the view below and their own labels,
--     not by being inserted into a venue view they have no venues for.
--
--     It also writes nothing into venue, venue_amenity_status or the access
--     chain. DS-09 is not government published. See 009 and the source card.
--
-- REVERSIBILITY
--     Additive only. No existing table, column, type, view or index is altered,
--     so the rollback is the DROP block at the foot of this file.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Types
-- ---------------------------------------------------------------------------

-- exact           Same sport, same wording as the venue vocabulary.
-- alias           Same sport, different wording. Calisthenics/Callisthenics.
-- narrower        A more specific form of a broader vocabulary sport whose
--                 venues genuinely host it. Only where the broader entry is a
--                 real parent, never where it is a sibling.
-- compound        One publisher label naming several vocabulary sports.
-- split           One publisher term covering several vocabulary entries the
--                 vocabulary distinguishes and the publisher does not.
-- added           A real sport the venue vocabulary does not contain, entering
--                 the vocabulary as its own entry rather than folded into a
--                 sibling.
-- added_adaptive  As added, and deliberately NOT folded into a non-adaptive
--                 parent. See the header.
-- not_a_sport     A published term that is not a sport — Art, Camps, Circus,
--                 Performing arts, Playground, Special Olympics. Kept as
--                 published, given no vocabulary entry.
-- unmapped        Could not be resolved. No row is in this state today; the
--                 value exists so a term that cannot be decided has somewhere to
--                 sit other than being deleted.
CREATE TYPE public.sport_crosswalk_relation AS ENUM (
    'exact',
    'alias',
    'narrower',
    'compound',
    'split',
    'added',
    'added_adaptive',
    'not_a_sport',
    'unmapped'
);

COMMENT ON TYPE public.sport_crosswalk_relation IS
    'How a publisher sport term relates to the venue sport vocabulary. Read with the note column, which records why each row was decided the way it was.';


-- ---------------------------------------------------------------------------
-- sport_crosswalk
-- ---------------------------------------------------------------------------

CREATE TABLE public.sport_crosswalk (
    source_id          text NOT NULL,
    term_key           text NOT NULL,
    term               text NOT NULL,
    publisher_slug     text NOT NULL,
    publisher_term_id  integer NOT NULL,
    relation           public.sport_crosswalk_relation NOT NULL,
    vocab_sport        text,
    adds_to_vocabulary boolean NOT NULL,
    note               text NOT NULL,

    -- A term that means no sport carries one row with a NULL target rather than
    -- no row at all. The absence of a row means UNREVIEWED, and the two must be
    -- distinguishable: the first is a decision, the second is a gap.
    CONSTRAINT sport_crosswalk_target_matches_relation CHECK (
        (relation IN ('not_a_sport', 'unmapped') AND vocab_sport IS NULL)
        OR
        (relation NOT IN ('not_a_sport', 'unmapped') AND vocab_sport IS NOT NULL)
    ),

    -- adds_to_vocabulary is not decoration: it is what tells the events sport
    -- list that this sport will never appear in sport_vocabulary, because no
    -- DS-01 venue records it.
    CONSTRAINT sport_crosswalk_added_matches_relation CHECK (
        adds_to_vocabulary = (relation IN ('added', 'added_adaptive'))
    ),

    -- THE RULE THE WHOLE TABLE EXISTS FOR, ENFORCED RATHER THAN TRUSTED.
    -- An adaptive or para sport maps to itself and to nothing else. Anyone who
    -- later tries to tidy the vocabulary by pointing Boccia at Bowls has to
    -- delete this constraint to do it, and deleting it is the conversation.
    CONSTRAINT sport_crosswalk_adaptive_is_never_folded CHECK (
        relation <> 'added_adaptive' OR vocab_sport = term
    ),

    CONSTRAINT sport_crosswalk_note_is_present CHECK (length(btrim(note)) > 0)
);

-- NO FOREIGN KEY ON source_id, ON PURPOSE. Every other table references
-- source(source_id), but those rows are inserted by a load run and this table is
-- seeded by a migration. The source register row for DS-09 is written by
-- scripts/load_run.py at the start of the first load, so a foreign key here
-- would make the migration fail on a fresh database purely because nothing has
-- been loaded into it yet.

-- One row per publisher term per vocabulary sport. coalesce rather than a plain
-- unique constraint because NULLs do not compare equal, so a plain constraint
-- would let a not_a_sport term be inserted twice.
CREATE UNIQUE INDEX sport_crosswalk_pk_idx
    ON public.sport_crosswalk (source_id, term_key, coalesce(vocab_sport, ''));

CREATE INDEX sport_crosswalk_term_key_idx ON public.sport_crosswalk (term_key);
CREATE INDEX sport_crosswalk_vocab_idx
    ON public.sport_crosswalk (lower(vocab_sport)) WHERE vocab_sport IS NOT NULL;

COMMENT ON TABLE public.sport_crosswalk IS
    'Reviewed mapping from the AAA Play activity_type taxonomy to the DS-01 venue sport vocabulary. Generated once from data/ingestion/crosswalks/ds09_sport_vocabulary.yaml and then read line by line; the YAML is the artefact to edit and a test compares the two. Many-to-many on purpose: one publisher term may name several vocabulary sports and several publisher terms may name one.';

COMMENT ON COLUMN public.sport_crosswalk.term_key IS
    'Joins to program_sport.sport_key. The publisher term slugified the same way the transformer slugifies it, with HTML entities already decoded: the API publishes "Bike riding, BMX &amp; cycling" and the key is bike_riding_bmx_cycling.';

COMMENT ON COLUMN public.sport_crosswalk.term IS
    'The publisher label as displayed, HTML entities decoded once at transform time. Never re-encode this to make it match a raw API response.';

COMMENT ON COLUMN public.sport_crosswalk.vocab_sport IS
    'The venue vocabulary sport this term means, or NULL where the term means no sport. NULL is a decision recorded with a reason in note; the absence of a row entirely is an unreviewed term, which is a different thing and is visible through sport_crosswalk_gap.';

COMMENT ON COLUMN public.sport_crosswalk.adds_to_vocabulary IS
    'True where the target is a sport the DS-01 venue register does not contain, so it will never appear in sport_vocabulary. Twenty terms are in this state, five of them adaptive or para sports held apart from their non-adaptive parents on purpose.';

COMMENT ON COLUMN public.sport_crosswalk.note IS
    'Why this row was decided the way it was. Required, because a row with no reason is a row nobody checked. Read it before changing a mapping.';


-- ---------------------------------------------------------------------------
-- Seed rows
--
-- Generated from data/ingestion/crosswalks/ds09_sport_vocabulary.yaml on
-- 15 September 2026: 82 publisher terms, 78 term-to-sport rows, plus 6 rows for
-- the terms that are not sports. Regenerate rather than hand-edit.
-- ---------------------------------------------------------------------------

INSERT INTO public.sport_crosswalk
    (source_id, term_key, term, publisher_slug, publisher_term_id,
     relation, vocab_sport, adds_to_vocabulary, note)
VALUES
    ('DS-09', 'adaptive_climbing', 'Adaptive climbing', 'adaptive-climbing', 1319,
     'added_adaptive', 'Adaptive climbing', true,
        'NOT Rock Climbing and NOT Bouldering. Adaptive climbing is climbing re-engineered around the '
        'climber: hauling systems, seated ascenders, trained belayers. Folding it into a climbing gym''s '
        'listing would tell a wheelchair user that any bouldering wall will do, which is the exact '
        'error this crosswalk exists to prevent. It enters the vocabulary as its own sport.'),
    ('DS-09', 'afl', 'AFL', 'afl', 1330,
     'alias', 'Australian Rules Football', false,
        'The register''s venue vocabulary writes the sport out in full. Same sport, different wording. '
        'Matches the backend SPORT_ALIASES entry.'),
    ('DS-09', 'aqua_aerobics', 'Aqua aerobics', 'aqua-aerobics', 1313,
     'narrower', 'Swimming', false,
        'Held in a pool, so a Swimming venue genuinely hosts it. Deliberately NOT mapped to Aerobics, '
        'which would send someone to a dry gym floor. The publisher label still displays, so the water '
        'is not lost from the screen.'),
    ('DS-09', 'archery', 'Archery', 'archery', 1312,
     'exact', 'Archery', false,
        'Same sport, same wording.'),
    ('DS-09', 'art', 'Art', 'art', 1358,
     'not_a_sport', NULL, false,
        'A creative programme, not a sport. Kept as published under its own label and given no '
        'vocabulary entry, because offering Art in a sport typeahead that is backed by playing surfaces '
        'would be misleading. See the program_sport table comment: some terms are not sports and are '
        'kept as published rather than filtered.'),
    ('DS-09', 'artistic_swimming', 'Artistic swimming', 'artistic-swimming', 1317,
     'narrower', 'Swimming', false,
        'A distinct sport, but a pool is a pool: a Swimming venue hosts it.'),
    ('DS-09', 'athletics', 'Athletics', 'athletics', 1274,
     'exact', 'Athletics', false,
        'Same sport, same wording.'),
    ('DS-09', 'badminton', 'Badminton', 'badminton', 1291,
     'exact', 'Badminton', false,
        'Same sport, same wording.'),
    ('DS-09', 'baseball', 'Baseball', 'baseball', 1338,
     'exact', 'Baseball', false,
        'Same sport, same wording.'),
    ('DS-09', 'basketball', 'Basketball', 'basketball', 1298,
     'exact', 'Basketball', false,
        'Same sport, same wording. The taxonomy has no wheelchair basketball term, so the publisher''s '
        'own PlayOn wheelchair basketball programmes sit under this one. That is the publisher''s grain '
        'and is not corrected here: inventing a term the source does not publish would be inventing a '
        'positive. The programme''s own label and access-need tags carry the detail.'),
    ('DS-09', 'biathlon', 'Biathlon', 'biathlon', 1293,
     'added', 'Biathlon', true,
        'Cross-country skiing and rifle shooting as one event. Neither Shooting Sports nor any snow '
        'sport in the venue vocabulary is a parent of it, and Modern Pentathlon is a different sport. '
        'Enters as its own entry. No activity carries it today.'),
    ('DS-09', 'bike_riding_bmx_cycling', 'Bike riding, BMX & cycling', 'bike-riding-bmx-cycling', 1333,
     'compound', 'Cycling', false,
        'One publisher label naming two vocabulary sports, which is why this file exists: the backend '
        'SPORT_ALIASES dict is one-to-one and can only reach Cycling, so a BMX search silently misses '
        'these programmes today. Both rows are emitted so a search for either sport finds the '
        'programme. Mountain biking is a separate publisher term and is not folded in here.'),
    ('DS-09', 'bike_riding_bmx_cycling', 'Bike riding, BMX & cycling', 'bike-riding-bmx-cycling', 1333,
     'compound', 'BMX', false,
        'One publisher label naming two vocabulary sports, which is why this file exists: the backend '
        'SPORT_ALIASES dict is one-to-one and can only reach Cycling, so a BMX search silently misses '
        'these programmes today. Both rows are emitted so a search for either sport finds the '
        'programme. Mountain biking is a separate publisher term and is not folded in here.'),
    ('DS-09', 'billiards_snooker_pool', 'Billiards, snooker & pool', 'billiards-snooker-pool', 1322,
     'alias', 'Snooker / Billiards / Pool', false,
        'Three cue games in one publisher label and the same three in one vocabulary entry, in a '
        'different order. One row, not three. The label arrives HTML-encoded as ''Billiards, snooker '
        '&amp; pool'' and is decoded once at transform time.'),
    ('DS-09', 'bocce', 'Bocce', 'bocce', 1326,
     'exact', 'Bocce', false,
        'Same sport, same wording. NOT Boccia. The two sit next to each other in this taxonomy and are '
        'different games; see the Boccia entry.'),
    ('DS-09', 'boccia', 'Boccia', 'boccia', 1277,
     'added_adaptive', 'Boccia', true,
        'BOCCIA IS NOT BOWLS AND IS NOT BOCCE. It is a Paralympic sport designed for athletes with '
        'severe physical impairment, played seated on an indoor court, with ramps and assistants '
        'permitted. Bowls and bocce are outdoor green and court games with no such provision. Mapping '
        'Boccia onto either would erase the one sport in this taxonomy built for the people this '
        'product is built for, and would send a Boccia player to a bowling green. It enters the '
        'vocabulary as its own sport.'),
    ('DS-09', 'bouldering', 'Bouldering', 'bouldering', 1328,
     'narrower', 'Rock Climbing / Abseiling (Indoor)', false,
        'Rope-free climbing at low height, hosted by the same indoor climbing venues the vocabulary '
        'entry describes. Not an adaptive sport, so folding it into its parent loses nothing. Adaptive '
        'climbing is handled separately and is NOT folded here.'),
    ('DS-09', 'bowls', 'Bowls', 'bowls', 1344,
     'alias', 'Lawn Bowls', false,
        'Matches the backend SPORT_ALIASES entry. Deliberately not also mapped to Carpet Bowls: the '
        'vocabulary distinguishes an outdoor green from an indoor carpet and the publisher does not, '
        'and mapping to both would put every lawn bowls programme in a carpet bowls search.'),
    ('DS-09', 'boxing', 'Boxing', 'boxing', 1316,
     'exact', 'Boxing', false,
        'Same sport, same wording.'),
    ('DS-09', 'bushwalking_hiking_or_walking', 'Bushwalking hiking or walking', 'bushwalking-hiking-or-walking', 1300,
     'added', 'Bushwalking, hiking or walking', true,
        'The venue vocabulary is a register of built sport facilities and has no walking entry at all; '
        'Open Space is a land classification, not a sport. Enters as its own entry. DISTINCT FROM '
        '''Walking and rolling'', which is the publisher''s wheelchair-inclusive term and keeps its own '
        'entry.'),
    ('DS-09', 'calisthenics', 'Calisthenics', 'calisthenics', 1340,
     'alias', 'Callisthenics', false,
        'Same sport, spelled with one l by the publisher and two by the venue register. A string '
        'comparison misses this; a reviewed file does not.'),
    ('DS-09', 'camps', 'Camps', 'camps', 1272,
     'not_a_sport', NULL, false,
        'A way of delivering a programme, not a sport. No vocabulary entry.'),
    ('DS-09', 'canoeing', 'Canoeing', 'canoeing', 1283,
     'exact', 'Canoeing', false,
        'Same sport, same wording.'),
    ('DS-09', 'circus', 'Circus', 'circus', 1367,
     'not_a_sport', NULL, false,
        'A performing art. No vocabulary entry.'),
    ('DS-09', 'cricket', 'Cricket', 'cricket', 1337,
     'exact', 'Cricket', false,
        'Mapped to the unqualified vocabulary entry only. Cricket (Indoor) is a separate entry and the '
        'publisher does not record the distinction, so claiming it would be an invented positive.'),
    ('DS-09', 'croquet', 'Croquet', 'croquet', 1284,
     'exact', 'Croquet', false,
        'Same sport, same wording.'),
    ('DS-09', 'dance', 'Dance', 'dance', 1323,
     'alias', 'Dancing', false,
        'Same activity, different wording.'),
    ('DS-09', 'darts', 'Darts', 'darts', 1288,
     'added', 'Darts', true,
        'Absent from the venue vocabulary, which registers playing surfaces and not club rooms. Enters '
        'as its own entry.'),
    ('DS-09', 'diving', 'Diving', 'diving', 1304,
     'exact', 'Diving', false,
        'Same sport, same wording. Springboard and platform diving, not scuba; the venue register uses '
        'the term the same way.'),
    ('DS-09', 'dragon_boat', 'Dragon boat', 'dragon-boat', 1290,
     'added', 'Dragon boat', true,
        'A crewed paddling sport of its own. Canoeing and Rowing are siblings, not parents, and a '
        'rowing shed is not a dragon boat club. Enters as its own entry.'),
    ('DS-09', 'equestrian', 'Equestrian', 'equestrian', 1305,
     'exact', 'Equestrian', false,
        'Same sport, same wording.'),
    ('DS-09', 'fencing', 'Fencing', 'fencing', 1347,
     'exact', 'Fencing', false,
        'Same sport, same wording.'),
    ('DS-09', 'fishing', 'Fishing', 'fishing', 1314,
     'added', 'Fishing', true,
        'Absent from the venue vocabulary. Enters as its own entry.'),
    ('DS-09', 'floor_curling', 'Floor curling', 'floor-curling', 1346,
     'added_adaptive', 'Floor curling', true,
        'An adapted, indoor, seated-playable form of curling used widely in disability and seniors '
        'programmes. The venue vocabulary has no curling entry of any kind, and the nearest bowls '
        'entries are a different game on a different surface. Enters as its own sport.'),
    ('DS-09', 'football_soccer', 'Football (soccer)', 'football-soccer', 1320,
     'alias', 'Soccer', false,
        'Matches the backend SPORT_ALIASES entry. Mapped to the unqualified vocabulary entry only; '
        'Soccer (Indoor Soccer / Futsal) is a separate entry and the publisher does not say which is '
        'meant.'),
    ('DS-09', 'general_fitness', 'General fitness', 'general-fitness', 1335,
     'alias', 'Fitness / Gymnasium Workouts', false,
        'Matches the backend SPORT_ALIASES entry.'),
    ('DS-09', 'goalball', 'Goalball', 'goalball', 1341,
     'added_adaptive', 'Goalball', true,
        'A Paralympic sport created for blind and vision-impaired athletes, played with a bell ball on '
        'a tactile- marked court by players wearing eyeshades. It has no non-adaptive parent anywhere '
        'in the venue vocabulary and must not be filed under an indoor ball sport. Enters as its own '
        'sport.'),
    ('DS-09', 'golf', 'Golf', 'golf', 1295,
     'exact', 'Golf', false,
        'Same sport, same wording. Disk Golf is a separate vocabulary entry and a different game.'),
    ('DS-09', 'gridiron', 'Gridiron', 'gridiron', 1308,
     'exact', 'Gridiron', false,
        'Same sport, same wording.'),
    ('DS-09', 'gym', 'Gym', 'gym', 1307,
     'alias', 'Fitness / Gymnasium Workouts', false,
        'Matches the backend SPORT_ALIASES entry. NOT Gymnastics, which the shared prefix makes a '
        'genuine hazard for a string matcher.'),
    ('DS-09', 'gymnastics', 'Gymnastics', 'gymnastics', 1292,
     'exact', 'Gymnastics', false,
        'Same sport, same wording.'),
    ('DS-09', 'hockey', 'Hockey', 'hockey', 1282,
     'exact', 'Hockey', false,
        'Field hockey in both registers. Ice Hockey, Inline Hockey and Underwater Hockey are separate '
        'vocabulary entries and none of them is meant here.'),
    ('DS-09', 'ice_hockey', 'Ice hockey', 'ice-hockey', 1324,
     'exact', 'Ice Hockey', false,
        'Same sport, different capitalisation.'),
    ('DS-09', 'ice_skating', 'Ice skating', 'ice-skating', 1301,
     'narrower', 'Skating', false,
        'The venue vocabulary''s Skating entry is not qualified and covers both ice rinks and skate '
        'parks, so it genuinely hosts this. The ambiguity is the venue register''s, recorded here rather '
        'than resolved by guesswork.'),
    ('DS-09', 'judo', 'Judo', 'judo', 1303,
     'exact', 'Judo', false,
        'Same sport, same wording.'),
    ('DS-09', 'karate', 'Karate', 'karate', 1297,
     'exact', 'Karate', false,
        'Same sport, same wording.'),
    ('DS-09', 'lacrosse', 'Lacrosse', 'lacrosse', 1289,
     'exact', 'Lacrosse', false,
        'Same sport, same wording.'),
    ('DS-09', 'martial_arts', 'Martial arts', 'martial-arts', 1306,
     'exact', 'Martial Arts', false,
        'Same activity, different capitalisation.'),
    ('DS-09', 'motor_sport', 'Motor sport', 'motor-sport', 1302,
     'alias', 'Motor Sports', false,
        'Same activity, singular against plural.'),
    ('DS-09', 'mountain_biking', 'Mountain biking', 'mountain-biking', 1299,
     'added', 'Mountain biking', true,
        'Deliberately not folded into Cycling. The venue vocabulary''s Cycling entry is velodromes and '
        'road circuits, which do not host mountain biking, and BMX is a different discipline again. '
        'Enters as its own entry.'),
    ('DS-09', 'netball', 'Netball', 'netball', 1331,
     'exact', 'Netball', false,
        'Mapped to the unqualified vocabulary entry only; Netball (Indoor) is a separate entry and the '
        'publisher does not record the distinction.'),
    ('DS-09', 'performing_arts', 'Performing arts', 'performing-arts', 1315,
     'not_a_sport', NULL, false,
        'Not a sport. No vocabulary entry.'),
    ('DS-09', 'petanque', 'Petanque', 'petanque', 1287,
     'added', 'Petanque', true,
        'A sibling of Bocce, not a child of it: different balls, different terrain, different rules. '
        'The vocabulary has Bocce and nothing else in the boules family, and a sibling is not a parent, '
        'so this enters as its own entry rather than being folded into a game it is not.'),
    ('DS-09', 'pickleball', 'Pickleball', 'pickleball', 1342,
     'added', 'Pickleball', true,
        'Absent from a venue register last published in December 2024, which is the fastest-growing '
        'sport in the country not being in the vocabulary rather than the programmes being wrong. Often '
        'played on converted tennis and badminton courts, but those are siblings and not parents. '
        'Enters as its own entry.'),
    ('DS-09', 'playground', 'Playground', 'playground', 1343,
     'not_a_sport', NULL, false,
        'A place, not a sport. Valuable on a listing and meaningless in a sport typeahead. No '
        'vocabulary entry.'),
    ('DS-09', 'rock_climbing', 'Rock climbing', 'rock-climbing', 1311,
     'alias', 'Rock Climbing / Abseiling (Indoor)', false,
        'The same sport. The venue entry carries an (Indoor) qualifier the publisher does not, which is '
        'recorded here rather than treated as a reason to leave the term unmapped. Adaptive climbing is '
        'NOT mapped here.'),
    ('DS-09', 'rowing', 'Rowing', 'rowing', 1329,
     'exact', 'Rowing', false,
        'Same sport, same wording.'),
    ('DS-09', 'rugby_touch', 'Rugby - touch', 'rugby-touch', 1325,
     'alias', 'Touch Football', false,
        'Same game, named for the code by the publisher and for the game by the venue register.'),
    ('DS-09', 'rugby_league', 'Rugby league', 'rugby-league', 1296,
     'exact', 'Rugby League', false,
        'Same sport, different capitalisation.'),
    ('DS-09', 'rugby_union', 'Rugby union', 'rugby-union', 1294,
     'exact', 'Rugby Union', false,
        'Same sport, different capitalisation.'),
    ('DS-09', 'sailing', 'Sailing', 'sailing', 1279,
     'exact', 'Sailing', false,
        'Same sport, same wording.'),
    ('DS-09', 'shooting', 'Shooting', 'shooting', 1321,
     'alias', 'Shooting Sports', false,
        'Same activity, different wording.'),
    ('DS-09', 'skateboarding', 'Skateboarding', 'skateboarding', 1327,
     'narrower', 'Skating', false,
        'Skate parks are registered under the venue vocabulary''s unqualified Skating entry, which '
        'therefore genuinely hosts this.'),
    ('DS-09', 'skiing', 'Skiing', 'skiing', 1278,
     'added', 'Skiing', true,
        'No snow sport of any kind in the venue vocabulary, which is a register of built facilities. '
        'Enters as its own entry.'),
    ('DS-09', 'snorkeling', 'Snorkeling', 'snorkeling', 1368,
     'added', 'Snorkeling', true,
        'Open water rather than a pool lane, and the vocabulary''s Diving entry is springboard diving, '
        'not underwater. Enters as its own entry.'),
    ('DS-09', 'snowboarding', 'Snowboarding', 'snowboarding', 1271,
     'added', 'Snowboarding', true,
        'See Skiing. Enters as its own entry.'),
    ('DS-09', 'snowshoeing', 'Snowshoeing', 'snowshoeing', 1339,
     'added', 'Snowshoeing', true,
        'See Skiing. Enters as its own entry.'),
    ('DS-09', 'softball', 'Softball', 'softball', 1310,
     'exact', 'Softball', false,
        'Same sport, same wording.'),
    ('DS-09', 'special_olympics', 'Special Olympics', 'special-olympics', 1345,
     'not_a_sport', NULL, false,
        'A multi-sport movement for people with intellectual disability, not a sport, and the second '
        'most used term in the taxonomy. It is kept as published and given no vocabulary entry: the '
        'programmes underneath it carry their real sports as additional terms, and inventing a Special '
        'Olympics row in a sport list would put a programme brand next to netball in a typeahead. A '
        'facet for it belongs in the product, not in the sport vocabulary.'),
    ('DS-09', 'squash', 'Squash', 'squash', 1275,
     'alias', 'Squash / Racquetball', false,
        'Same sport, paired with racquetball.'),
    ('DS-09', 'surfing', 'Surfing', 'surfing', 1286,
     'added', 'Surfing', true,
        'Surf Life Saving is a different activity with different clubs, so it is not a parent. Enters '
        'as its own entry.'),
    ('DS-09', 'swimming', 'Swimming', 'swimming', 1334,
     'exact', 'Swimming', false,
        'Same sport, same wording.'),
    ('DS-09', 'table_tennis', 'Table tennis', 'table-tennis', 1309,
     'exact', 'Table Tennis', false,
        'Same sport, different capitalisation.'),
    ('DS-09', 'tennis', 'Tennis', 'tennis', 1280,
     'split', 'Tennis (Outdoor)', false,
        'THE VOCABULARY HAS NO UNQUALIFIED TENNIS ENTRY. Both rows are emitted because choosing one '
        'would hide every venue of the other kind from a tennis programme, and the publisher does not '
        'record which is meant. This is the other case the one-to-one SPORT_ALIASES dict cannot '
        'express.'),
    ('DS-09', 'tennis', 'Tennis', 'tennis', 1280,
     'split', 'Tennis (Indoor)', false,
        'THE VOCABULARY HAS NO UNQUALIFIED TENNIS ENTRY. Both rows are emitted because choosing one '
        'would hide every venue of the other kind from a tennis programme, and the publisher does not '
        'record which is meant. This is the other case the one-to-one SPORT_ALIASES dict cannot '
        'express.'),
    ('DS-09', 'tenpin_bowling', 'Tenpin bowling', 'tenpin-bowling', 1270,
     'alias', 'Ten Pin Bowling', false,
        'Same sport, spaced differently. Matches the backend SPORT_ALIASES entry.'),
    ('DS-09', 'triathlon', 'Triathlon', 'triathlon', 1318,
     'added', 'Triathlon', true,
        'Swim, ride and run as one event. Its three legs are separate vocabulary entries and none is a '
        'parent. Modern Pentathlon is a different sport. Enters as its own entry.'),
    ('DS-09', 'ultimate_frisbee', 'Ultimate (frisbee)', 'ultimate-frisbee', 1281,
     'narrower', 'Flying Disk', false,
        'The venue register''s Flying Disk entry is the generic disc-sport classification and hosts '
        'this. Disk Golf is the other disc sport and is a separate entry.'),
    ('DS-09', 'volleyball', 'Volleyball', 'volleyball', 1332,
     'exact', 'Volleyball', false,
        'Same sport, same wording. Beach Volleyball is a separate vocabulary entry and the publisher '
        'does not say the sand is meant.'),
    ('DS-09', 'walking_and_rolling', 'Walking and rolling', 'walking-and-rolling', 1285,
     'added_adaptive', 'Walking and rolling', true,
        '''ROLLING'' IS THE WHEELCHAIR, AND IT IS THE WHOLE POINT OF THE TERM. Folding this into '
        'Bushwalking hiking or walking would delete the one word in the taxonomy that tells a '
        'wheelchair user the route was thought about for them. Twenty-three programmes carry it. Enters '
        'as its own sport, separate from the walking term.'),
    ('DS-09', 'water_polo', 'Water polo', 'water-polo', 1336,
     'exact', 'Water Polo', false,
        'Same sport, different capitalisation.'),
    ('DS-09', 'water_skiing', 'Water skiing', 'water-skiing', 1269,
     'exact', 'Water Skiing', false,
        'Same sport, different capitalisation.'),
    ('DS-09', 'weightlifting', 'Weightlifting', 'weightlifting', 1273,
     'narrower', 'Fitness / Gymnasium Workouts', false,
        'A gym is a genuine parent here: the vocabulary entry is where the equipment is. Body Building '
        'is a sibling and is not used.'),
    ('DS-09', 'wrestling', 'Wrestling', 'wrestling', 1276,
     'added', 'Wrestling', true,
        'The venue register treats combat sports as siblings rather than children of Martial Arts, '
        'which sits beside Boxing, Judo, Karate and Tae Kwon Do rather than above them. Wrestling is '
        'absent, so it enters as its own entry.');


-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- The many-to-many link, resolved. One row per programme per vocabulary sport,
-- plus one row per programme per publisher term that maps to no sport, so a
-- programme tagged only Art or Playground does not vanish from this view.
--
-- LEFT JOIN, NOT INNER. A publisher term with no crosswalk row is a term nobody
-- has reviewed yet, and it comes through here with a NULL vocab_sport and its
-- own label intact. An inner join would delete exactly the rows somebody needs
-- to see. See sport_crosswalk_gap below for the list of them.
CREATE VIEW public.program_sport_vocabulary AS
SELECT ps.program_id,
       ps.sport_key,
       ps.sport_label,
       cw.vocab_sport,
       cw.relation,
       coalesce(cw.adds_to_vocabulary, false) AS adds_to_vocabulary,
       cw.term_key IS NULL                    AS unreviewed
  FROM public.program_sport ps
  LEFT JOIN public.sport_crosswalk cw
    ON cw.term_key  = ps.sport_key
   AND cw.source_id = ps.source_id;

COMMENT ON VIEW public.program_sport_vocabulary IS
    'Programmes joined to the venue sport vocabulary through the reviewed crosswalk. Query this rather than program_sport when a sport filter has to match the venue vocabulary: a search for either Cycling or BMX finds a "Bike riding, BMX and cycling" programme, and a search for either of the two tennis entries finds a Tennis programme. vocab_sport is NULL where the term means no sport and where the term has not been reviewed; the unreviewed flag separates them.';


-- Unreviewed publisher terms, which is what a new term upstream looks like from
-- the database side. THIS VIEW IS THE POINT OF THE LEFT JOIN ABOVE. A term the
-- publisher adds next month is not dropped and is not guessed at: it appears
-- here with a count, and the fix is a reviewed row in the YAML.
--
-- The transformer makes the same gap visible on the way in, as a SCHEMA_VIOLATION
-- quarantine row per unreviewed term. Two places, because the transformer sees
-- it during a load run and this view answers the question afterwards.
CREATE VIEW public.sport_crosswalk_gap AS
SELECT ps.source_id,
       ps.sport_key,
       min(ps.sport_label) AS sport_label,
       count(*)            AS program_count
  FROM public.program_sport ps
 WHERE NOT EXISTS (
           SELECT 1
             FROM public.sport_crosswalk cw
            WHERE cw.term_key  = ps.sport_key
              AND cw.source_id = ps.source_id
       )
 GROUP BY ps.source_id, ps.sport_key;

COMMENT ON VIEW public.sport_crosswalk_gap IS
    'Publisher sport terms carried by loaded programmes that no reviewed crosswalk row covers. Expected to be empty. A non-empty result is a taxonomy change upstream, and the fix is to add the term to data/ingestion/crosswalks/ds09_sport_vocabulary.yaml with a decided relation, not to widen a match.';

COMMIT;


-- ============================================================================
-- ROLLBACK
--
--   BEGIN;
--   DROP VIEW  IF EXISTS public.sport_crosswalk_gap;
--   DROP VIEW  IF EXISTS public.program_sport_vocabulary;
--   DROP TABLE IF EXISTS public.sport_crosswalk;
--   DROP TYPE  IF EXISTS public.sport_crosswalk_relation;
--   COMMIT;
-- ============================================================================
