"""
tests/test_ds09_count_drift.py

The two DS-09 count guards, and the difference between them.

WHY BOTH GUARDS EXIST
    DS-01 to DS-08 are file downloads. A truncated one changes its size, breaks
    its pinned SHA-256 and fails before it is written. DS-09 is eighteen HTTP
    responses stitched into one document: every page is a 200, a short pull
    produces a valid smaller document with a perfectly good hash, and nothing in
    the pipeline notices that half the register went missing.

    The truncation guard catches a pull that disagrees with the publisher's own
    X-WP-Total in the same breath, and refuses it. The drift guard compares two
    different days and only warns, because a register is allowed to change.
    Confusing the two — raising on drift, or warning on truncation — is the
    mistake these tests exist to prevent.

No network. Every request is served by a fake transport.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from ingestion.extractors import aaaplay

SOURCE_CARD = Path(__file__).resolve().parents[1] / "sources" / "DS-09_aaaplay.yaml"

# The live figures of 15 September 2026, and the same figures the source card
# records. Stated here so a change to either is a conversation.
VERIFIED = {
    "activity": 532,
    "facility": 552,
    "organisation": 178,
    "activity_type": 82,
    "age_range": 6,
    "lga": 102,
    "region": 16,
}


def fake_api(counts: dict[str, int], totals: dict[str, int] | None = None):
    """A transport that serves paginated WordPress collections from counts.

    `totals` overrides what X-WP-Total claims, which is how a truncated pull is
    simulated: the header says one thing and the pages deliver another.
    """
    stated = {**counts, **(totals or {})}

    def transport(url: str) -> tuple[int, dict[str, str], bytes]:
        collection = url.rsplit("/", 1)[-1].split("?")[0]
        page = int(url.split("page=")[-1])

        held = counts[collection]
        total = stated[collection]
        pages = max(1, -(-total // aaaplay.PER_PAGE))

        start = (page - 1) * aaaplay.PER_PAGE
        rows = [{"id": i} for i in range(start, min(start + aaaplay.PER_PAGE, held))]

        headers = {"x-wp-total": str(total), "x-wp-totalpages": str(pages)}

        return 200, headers, json.dumps(rows).encode("utf-8")

    return transport


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """The collector pauses politely between requests. Tests need not wait."""
    monkeypatch.setattr(aaaplay.time, "sleep", lambda _seconds: None)


# The truncation guard


def test_a_complete_collection_is_returned() -> None:
    records = aaaplay._collect_paginated("activity", fake_api({"activity": 532}))

    assert len(records) == 532


def test_a_lost_page_is_refused() -> None:
    """The dangerous case: 200s all the way, a hundred records short.

    This is the one that has to raise. A truncated collection written as the
    current state of the register deletes programmes, and every other signal in
    the pipeline says the fetch succeeded.
    """
    transport = fake_api({"activity": 432}, totals={"activity": 532})

    with pytest.raises(aaaplay.FetchError, match="X-WP-Total"):
        aaaplay._collect_paginated("activity", transport)


def test_more_records_than_the_publisher_claims_is_also_refused() -> None:
    """A long read is a paging bug rather than a windfall."""
    transport = fake_api({"activity": 632}, totals={"activity": 532})

    with pytest.raises(aaaplay.FetchError, match="X-WP-Total"):
        aaaplay._collect_paginated("activity", transport)


def test_a_record_published_mid_pull_does_not_fail_the_fetch() -> None:
    """A six-page pull takes seconds and providers edit during them.

    Failing a weekly job over one record would make the guard something people
    route around, which is worse than not having it.
    """
    transport = fake_api({"activity": 531}, totals={"activity": 532})

    assert len(aaaplay._collect_paginated("activity", transport)) == 531


def test_an_empty_collection_is_still_refused() -> None:
    with pytest.raises(aaaplay.FetchError, match="no records"):
        aaaplay._collect_paginated("activity", fake_api({"activity": 0}))


def test_an_unreadable_total_header_does_not_silently_pass(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def transport(url: str) -> tuple[int, dict[str, str], bytes]:
        return (
            200,
            {"x-wp-total": "lots", "x-wp-totalpages": "1"},
            json.dumps([{"id": 1}]).encode("utf-8"),
        )

    with caplog.at_level("WARNING"):
        records = aaaplay._collect_paginated("activity", transport)

    assert len(records) == 1
    assert "could not be checked" in caplog.text


# record_counts


def test_counts_are_derived_from_the_payload_that_was_hashed() -> None:
    payload = aaaplay.collect(fake_api(VERIFIED))

    assert aaaplay.record_counts(payload) == VERIFIED


def test_the_payload_is_byte_identical_for_an_unchanged_register() -> None:
    """The whole no-change path rests on this, and so does the drift baseline."""
    assert aaaplay.collect(fake_api(VERIFIED)) == aaaplay.collect(fake_api(VERIFIED))


# The drift guard


def test_no_previous_figures_is_reported_as_no_baseline_not_as_a_pass() -> None:
    result = aaaplay.check_count_drift(VERIFIED, None)

    assert result["status"] == "no_baseline"
    assert result["previous"] is None
    assert result["baseline"] is None


def test_the_result_says_which_baseline_it_used() -> None:
    """A card figure and last week's manifest are not worth the same.

    The card is dated and ages as the register moves; the manifest is what the
    pull actually collected seven days ago. A reader has to be able to tell
    which comparison they are looking at.
    """
    from_card = aaaplay.check_count_drift(VERIFIED, VERIFIED, baseline="source_card")

    assert from_card["baseline"] == "source_card"
    assert aaaplay.check_count_drift(VERIFIED, VERIFIED)["baseline"] == "previous_run"


def test_the_card_figures_would_catch_a_badly_short_first_pull() -> None:
    """The fallback baseline earning its place on a run with no manifest."""
    short = {**VERIFIED, "activity": 332}

    result = aaaplay.check_count_drift(short, VERIFIED, baseline="source_card")

    assert result["status"] == "drift"
    assert result["breached"] == ["activity"]


def test_one_lost_page_sits_inside_the_band_which_is_why_the_other_guard_exists() -> None:
    """A finding, written down rather than left for somebody to rediscover.

    A single lost page of the activity collection is 100 records out of 532,
    which is 18.8% and therefore INSIDE the 20% band. The drift guard does not
    catch it and was never going to: a 20% band is a sane-range check, not a
    truncation detector. The X-WP-Total comparison in _collect_paginated is what
    catches a lost page, deterministically and in the same request.

    If somebody later proposes removing that check because "the drift guard
    covers it", this test is the answer. Narrowing the band instead would make
    the weekly job cry wolf every time the register had a busy fortnight.
    """
    result = aaaplay.check_count_drift({**VERIFIED, "activity": 432}, VERIFIED)

    assert result["status"] == "ok"
    assert result["collections"]["activity"]["change_pct"] == -18.8

    transport = fake_api({"activity": 432}, totals={"activity": 532})

    with pytest.raises(aaaplay.FetchError, match="X-WP-Total"):
        aaaplay._collect_paginated("activity", transport)


def test_a_register_that_barely_moved_passes() -> None:
    previous = {**VERIFIED, "activity": 530}

    result = aaaplay.check_count_drift(VERIFIED, previous)

    assert result["status"] == "ok"
    assert result["breached"] == []
    assert result["collections"]["activity"]["change_pct"] == 0.38


def test_a_swing_beyond_the_band_is_reported_as_drift(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Half the register gone. Loud, and still written."""
    halved = {**VERIFIED, "activity": 266}

    with caplog.at_level("ERROR"):
        result = aaaplay.check_count_drift(halved, VERIFIED)

    assert result["status"] == "drift"
    assert result["breached"] == ["activity"]
    assert result["collections"]["activity"]["change_pct"] == -50.0

    # The observability alarms read this event name out of the log stream.
    assert "COUNT_DRIFT" in caplog.text


def test_drift_warns_and_never_raises() -> None:
    """Stated as its own test because it is a decision, not an oversight.

    Refusing to write would lose the payload a person needs in order to decide
    whether the register really shrank, and would lose the manifest the NEXT run
    compares against — so one bad week would blind the guard for every week
    after it.
    """
    assert aaaplay.check_count_drift({"activity": 1}, {"activity": 532})["status"] == "drift"


def test_a_growth_spike_breaches_in_the_other_direction() -> None:
    result = aaaplay.check_count_drift({**VERIFIED, "activity": 900}, VERIFIED)

    assert result["breached"] == ["activity"]


def test_the_band_edges_are_where_they_are_claimed_to_be() -> None:
    at_the_edge = aaaplay.check_count_drift({"activity": 400}, {"activity": 500})
    just_over = aaaplay.check_count_drift({"activity": 399}, {"activity": 500})

    assert at_the_edge["status"] == "ok"
    assert just_over["status"] == "drift"


def test_a_small_collection_is_reported_but_not_called_a_breach() -> None:
    """One term added to a six-term taxonomy is a 17% move and means nothing."""
    result = aaaplay.check_count_drift({**VERIFIED, "age_range": 7}, VERIFIED)

    assert result["status"] == "ok"
    assert result["collections"]["age_range"]["change_pct"] == 16.67
    assert result["collections"]["age_range"]["breached"] is False


def test_a_collection_that_stopped_being_collected_is_a_breach() -> None:
    """No percentage to state, and the worst outcome of the lot."""
    without_facilities = {key: value for key, value in VERIFIED.items() if key != "facility"}

    result = aaaplay.check_count_drift(without_facilities, VERIFIED)

    assert result["status"] == "drift"
    assert result["breached"] == ["facility"]
    assert result["disappeared"] == ["facility"]


def test_a_new_collection_is_recorded_rather_than_treated_as_a_fault() -> None:
    result = aaaplay.check_count_drift({**VERIFIED, "event": 9}, VERIFIED)

    assert result["status"] == "ok"
    assert result["appeared"] == ["event"]


# The source card


def test_the_source_card_records_the_verified_figures() -> None:
    """The card is the baseline a first run has, so it has to be right."""
    card = yaml.safe_load(SOURCE_CARD.read_text(encoding="utf-8"))

    coverage = card["coverage"]

    assert coverage["records_by_collection"] == VERIFIED
    assert coverage["records_total"] == VERIFIED["activity"]
    assert coverage["counts_verified_at"].isoformat() == "2026-09-15"


def test_the_card_still_says_no_licence_is_stated() -> None:
    """The licence block is a deliberate position and is easy to tidy away.

    It records that this source publishes no licence instrument, which is an
    absence recorded as an absence. Nothing in this task may soften it into a
    value that makes the card resemble DS-01 to DS-08.
    """
    card = yaml.safe_load(SOURCE_CARD.read_text(encoding="utf-8"))

    licence: dict[str, Any] = card["licence"]

    assert licence["name"] == "No licence stated"
    assert licence["version"] is None
    assert licence["restricts_caching"] is None
    assert licence["restricts_redistribution"] is None
    assert licence["restricts_derived_works"] is None
