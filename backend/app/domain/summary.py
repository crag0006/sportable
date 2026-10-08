"""The Read Aloud summary, built from the record rather than from the page (US3.3).

THE ONE RULE — "unknown is spoken, never skipped."

AC3.3.1 asks Read Aloud to speak a short summary of a page's important
information rather than the whole page. The obvious implementation is to walk
the DOM and read what is on screen, and it is the wrong one twice over:

  * What gets spoken would depend on layout. Move a tile into a collapsed
    panel and it stops being read out, silently, with no test that notices.
  * A facility that is absent from the audio reads, to somebody who cannot see
    the label, as a facility that is not there. That is the failure AC4.2.3
    exists to prevent, in the one channel where the reader has no way to check.

So the summary is assembled here, from the same response objects the page
renders, and all four facility statuses are always present — including the
ones that say "no published information", which is the sentence that stops an
unknown being heard as a no.

WHY AN ARRAY AND NOT A PARAGRAPH
    AC3.3.3 requires the sentence currently being spoken to be highlighted. If
    the frontend were handed one prose blob it would have to split it back into
    sentences, and sentence splitting on ``121 Cramer St.`` or ``Mt. Evelyn``
    or ``9.30 a.m.`` drifts by a clause — the highlight lands on the wrong
    words at exactly the moment the reader is relying on it. One complete
    sentence per array element hands over the boundaries instead of asking for
    them to be guessed. Nothing below ever emits an element containing two
    sentences.

WHY THERE IS A WORD CAP
    Speech runs at roughly 150 words a minute, and AC3.3.1 rules out reading
    the whole page. ``SUMMARY_WORD_CAP`` keeps the summary to about a minute.
    Trimming drops OPTIONAL sentences only, newest first; the identity, the
    four facility statuses and the timing are never dropped, because a summary
    that fits inside a minute by leaving out a toilet is not a shorter summary,
    it is a wrong one.
"""

from dataclasses import dataclass
from datetime import date

from app.schemas.common import FacilityOut
from app.schemas.events import EventOut
from app.schemas.venues import VenueCardOut

# Roughly one minute of speech at a typical screen-reader rate.
SUMMARY_WORD_CAP = 150

MONTHS: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# Said once at the end rather than repeated on every facility sentence.
DISTANCE_CAVEAT = (
    "Distances are straight-line, not walking distance, and nothing here is checked live."
)

NO_INFORMATION_CLAUSE = "no published information"


@dataclass(frozen=True)
class _Sentence:
    """One spoken sentence and whether the word cap may drop it.

    ``required=True`` means this sentence carries something the reader cannot
    safely be left without: what the page is about, a facility status, or when
    the thing happens.
    """

    text: str
    required: bool = True


def _words(text: str) -> int:
    return len(text.split())


def _apply_cap(sentences: list[_Sentence], cap: int = SUMMARY_WORD_CAP) -> list[str]:
    """Trim to the cap by dropping optional sentences from the end.

    Required sentences are never dropped. If they alone exceed the cap the
    summary runs slightly long, which is the right way round: a reader would
    rather hear ten seconds more than not hear whether there is a toilet.
    """
    kept = list(sentences)
    total = sum(_words(s.text) for s in kept)
    while total > cap:
        droppable = [i for i, s in enumerate(kept) if not s.required]
        if not droppable:
            break
        removed = kept.pop(droppable[-1])
        total -= _words(removed.text)
    return [s.text for s in kept]


# ------------------------------------------------------------- facilities
def _basis_clause(tile: FacilityOut) -> str:
    """How we know, in the reader's words rather than the database's.

    ``publisher_attribute`` and ``spatial_proximity`` are not interchangeable
    and the difference matters on the phone from the car park: one is the venue
    saying it has a toilet, the other is a separate public toilet that happens
    to be close. Never spoken as the same thing.
    """
    source = tile.source.name if tile.source is not None else None
    if tile.basis == "publisher_attribute":
        return f"the venue's own record from {source}" if source else "the venue's own record"
    if tile.basis == "spatial_proximity":
        if source:
            return f"the nearest mapped facility from {source}"
        return "the nearest mapped facility"
    return NO_INFORMATION_CLAUSE


def _facility_sentence(tile: FacilityOut) -> str:
    """One complete sentence for one tile. Always produced, for all four kinds."""
    label = tile.label
    if tile.display == "no_published_information":
        # The sentence this whole module exists for. Spoken in full, in the
        # same position in the list as a confirmed facility would occupy, so
        # the absence of information is heard rather than inferred.
        return f"{label}: {NO_INFORMATION_CLAUSE}."
    if tile.display == "at_venue":
        head = "at the venue"
    elif tile.display == "nearby":
        head = f"a public one {tile.distance_m} metres away"
    elif tile.display == "beyond_limit":
        head = (
            f"nearest recorded one {tile.distance_m} metres away, "
            f"beyond your {tile.distance_limit_m} metre limit"
        )
    elif tile.display == "not_available_alternative" and tile.alternative is not None:
        head = (
            "not at the venue, and the nearest public one is "
            f"{tile.alternative.distance_m} metres away"
        )
    else:
        head = "recorded as not available here"
    return f"{label}: {head}, {_basis_clause(tile)}."


def _facility_sentences(tiles: list[FacilityOut]) -> list[_Sentence]:
    return [_Sentence(_facility_sentence(tile), required=True) for tile in tiles]


# ------------------------------------------------------------------ venue
def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _venue_identity(card: VenueCardOut) -> str:
    where = ", ".join(p for p in (card.suburb, card.lga) if p)
    place = f" in {where}" if where else ""
    # Three sports is enough to say what the place is for. A venue listing
    # eleven would otherwise spend a third of the minute on a list nobody is
    # waiting for, and push the facility statuses towards the cap.
    sports = [s.lower() for s in card.sports[:3]]
    for_sports = f", for {_join(sports)}" if sports else ""
    return f"{card.name} is a sports venue{place}{for_sports}."


def venue_summary_sentences(card: VenueCardOut) -> list[str]:
    """AC3.3.1 - the venue page in about a minute of speech.

    Takes the finished response object rather than the repository row on
    purpose: the summary then cannot describe anything the page does not show,
    and the four facility sentences are read off the very tiles that were
    rendered, at the distance band the request asked for.
    """
    sentences: list[_Sentence] = [_Sentence(_venue_identity(card))]

    if card.address:
        sentences.append(_Sentence(f"The address is {card.address}.", required=False))
    if card.distance_m is not None and card.reference_point is not None:
        sentences.append(
            _Sentence(
                f"It is about {card.distance_m} metres from {card.reference_point.label}.",
                required=False,
            )
        )

    sentences.extend(_facility_sentences(card.facilities))

    upcoming = card.upcoming_events
    if upcoming.count == 1:
        sentences.append(_Sentence("One event is listed at this venue."))
    elif upcoming.count > 1:
        sentences.append(_Sentence(f"{upcoming.count} events are listed at this venue."))
    else:
        sentences.append(_Sentence("No events are listed at this venue right now.", required=False))

    sentences.append(_Sentence(DISTANCE_CAVEAT, required=False))
    return _apply_cap(sentences)


# ------------------------------------------------------------------ event
def _long_date(iso: str) -> str:
    """``2026-09-19`` -> ``19 September 2026``. No full stops, deliberately.

    A spoken sentence that contains an abbreviation with a full stop is a
    sentence the frontend might re-split on, and AC3.3.3's highlight would then
    land mid-clause.
    """
    parsed = date.fromisoformat(iso)
    return f"{parsed.day} {MONTHS[parsed.month - 1]} {parsed.year}"


def _event_identity(event: EventOut) -> str:
    sport = (event.sport or event.sport_raw or "").lower()
    noun = "weekly program" if event.kind == "program" else "fixture"
    what = f"a {sport} {noun}" if sport else f"a {noun}"
    run_by = f", run by {event.organisation}" if event.organisation else ""
    return f"{event.title} is {what}{run_by}."


def _event_place(event: EventOut) -> list[_Sentence]:
    venue = event.venue
    if venue.name is None:
        return [_Sentence("The publisher did not record a venue for this event.")]
    if not venue.matched:
        # AC4.2.3 / AC5.2.2. Said before the four tiles, so the four "no
        # published information" sentences that follow have their reason
        # already spoken rather than sounding like a data outage.
        return [
            _Sentence(f"It is at {venue.name}, which is not in our venue list."),
            _Sentence(
                "We have no published access information for it, "
                "so all four facilities are unknown."
            ),
        ]
    where = ", ".join(p for p in (venue.name, venue.address) if p)
    return [_Sentence(f"It is at {where}.")]


def _event_timing(event: EventOut) -> _Sentence:
    """When it runs. Required: a summary that omits this sends nobody anywhere."""
    if event.recurrence is not None:
        if event.recurrence.days_stated:
            return _Sentence(f"It runs on {event.recurrence.summary}.")
        return _Sentence("The publisher did not state which days it runs.")
    if event.date_local:
        when = _long_date(event.date_local)
        if event.time_local:
            return _Sentence(f"It starts on {when} at {event.time_local}.")
        return _Sentence(f"It is on {when}.")
    return _Sentence("The publisher did not state when it runs.")


def event_summary_sentences(event: EventOut) -> list[str]:
    """AC3.3.1 - the event page in about a minute of speech.

    Same four facility sentences as the venue page, from the same tiles, so an
    event and its venue can never be heard to disagree.
    """
    sentences: list[_Sentence] = [_Sentence(_event_identity(event))]

    # A cancellation outranks everything except the name of the thing that was
    # cancelled, so it is spoken second and can never be trimmed.
    if event.status in ("CANCELLED", "ABANDONED"):
        sentences.append(_Sentence(f"This event is {event.status_label.lower()}."))

    sentences.extend(_event_place(event))
    sentences.extend(_facility_sentences(event.access.facilities))
    sentences.append(_event_timing(event))

    if event.price == "free":
        sentences.append(_Sentence("It is free.", required=False))
    elif event.price == "paid":
        sentences.append(_Sentence("There is a cost to take part.", required=False))

    sentences.append(_Sentence(DISTANCE_CAVEAT, required=False))
    return _apply_cap(sentences)
