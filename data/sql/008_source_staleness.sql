-- sql/008_source_staleness.sql
--
-- The per-source staleness threshold (HLD principle 3, AC3.3.3).
--
-- Every fact the API returns carries its publisher's last-updated date and a
-- possibly_out_of_date flag. The flag needs a threshold, and the threshold is
-- a property of the source: a weekly-refreshed programme list is stale after
-- a fortnight, a boundary layer the ABS republishes annually is not. The
-- value comes from the register card's cadence when the source is seeded.
-- While it is NULL the API applies its configured default and says so
-- (stale_after_days is echoed on every provenance object).
--
-- Additive only. Rollback: ALTER TABLE source DROP COLUMN stale_after_days.

BEGIN;

ALTER TABLE source
    ADD COLUMN stale_after_days integer;

COMMENT ON COLUMN source.stale_after_days IS
    'Days after publisher_last_updated beyond which every fact from this source is marked possibly out of date. From the register card cadence. NULL = the API default applies.';

COMMIT;
