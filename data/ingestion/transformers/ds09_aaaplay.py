"""
ingestion/transformers/ds09_aaaplay.py

Transforms the raw DS-09 AAA Play data into program, venue, organisation and
link rows.

DS-09 is the events epic's only source. It is NOT part of the access chain and
contributes nothing to any facility status.

WHY THIS TRANSFORMER LOOKS DIFFERENT FROM ds01 AND ds02
    Those two take one dataframe, because their sources are one file. AAA Play
    is a WordPress REST API and arrives as three post types plus four
    taxonomies, so transform() takes the lists the fetch step wrote and joins
    them here. The output contract is unchanged: dataframes plus quarantine
    plus stats, and no database, file or network access anywhere in this module.

THE ONE RULE THAT MATTERS MOST
    Nothing this module emits may ever become a publication_status. Reclink is
    a not-for-profit delivering a government-funded program, and the register's
    standing position is that government records are the only thing that can
    produce a confirmed. The facility booleans below describe attributes no
    other source covers, which makes them tempting. They are display material
    with their own attribution, and they stay out of venue, venue_amenity_status
    and venue_access_chain. See DS-09 known_limitations.

WHAT IS DELIBERATELY THROWN AWAY
    contact_email and contact_phone      personal information, see privacy note
    facility_changing_places             provably wrong, see _FACILITY_BOOLEANS
    every false in a facility boolean    unticked box, not a recorded absence
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

SOURCE_ID = "DS-09"

# Post types as the fetch step names them in the raw zone.
POST_ACTIVITY = "activity"
POST_FACILITY = "facility"
POST_ORGANISATION = "organisation"

# Taxonomies resolved from term id to term name. Registered here rather than
# discovered, so an unexpected taxonomy appearing upstream is visible as a miss
# in the stats rather than silently widening the output.
TAXONOMIES = ("activity_type", "age_range", "lga", "region")

# The 16 facility booleans that are loaded, with the display label each one
# carries on the venue page.
#
# facility_changing_places is ABSENT ON PURPOSE and must not be added back.
# The source reports it true for 275 of 552 facilities. Changing Places is an
# accredited standard: a facility must be assessed against the Design
# Specification, issued a Statement of Compliance, and listed on the National
# Public Toilet Map, which is DS-02, where the Victorian count is 163. A source
# cannot hold 275 of something the authoritative register counts 163 of
# statewide, so providers are reading the field as "has a change room". The
# term is also a trade mark held by the State of Victoria. DS-02 stays the only
# Changing Places evidence in this project.
_FACILITY_BOOLEANS: dict[str, str] = {
    "facility_wheelchair_accessible": "Wheelchair accessible",
    "facility_accessible_changerooms": "Accessible changerooms",
    "facility_lift_access": "Lift access",
    "facility_hydrotherapy_pool": "Hydrotherapy pool",
    "facility_ramps_to_access_pools": "Ramp access to pool",
    "facility_pool_hoist": "Pool hoist",
    "facility_aquatic_wheelchair": "Aquatic wheelchair",
    "facility_accessible_gym_equipment": "Accessible gym equipment",
    "facility_hearing_loops": "Hearing loop",
    "facility_sensory_space": "Sensory space",
    "facility_pictorial_communication_aids": "Pictorial communication aids",
    "facility_cerge_platform": "CERGE platform",
    "facility_staff_trained": "Staff trained in disability support",
    "facility_companion_card_accepted": "Companion Card accepted",
    "facility_carer_card_discounts": "Carer Card discounts",
}

# facility_cafe also exists on the record and is deliberately not loaded: it is
# an amenity, not an access attribute, and mixing it into the accessibility
# block would imply the publisher asserted something about access that it did
# not. Add it as its own field if the venue page ever wants it.

# The publisher stores multi-value ACF fields as slugs, not labels, while
# activity_welcoming stores display strings. Mapping here rather than
# prettifying the slug at render time, because "non_disability_everyone" does
# not title-case into anything a person would write.
_ACCESS_NEED_LABELS: dict[str, str] = {
    "wheelchair_accessible": "Wheelchair accessible",
    "physical_limitation": "Physical limitation",
    "blind_or_vision_impaired": "Blind or vision impaired",
    "deaf_or_hearing_impaired": "Deaf or hearing impaired",
    "autistic_or_neurodivergent": "Autistic or neurodivergent",
    "intellectual_disability": "Intellectual disability",
    "psycho_social": "Psycho-social",
    "sensory_friendly": "Sensory friendly",
    "immune_compromised": "Immunocompromised",
    "disability_specific": "Disability specific",
    "non_disability_everyone": "Open to everyone",
    "auslan": "Auslan",
}

_TIME_OF_DAY_LABELS: dict[str, str] = {
    "morning": "Morning",
    "afternoon": "Afternoon",
    "evening": "Evening",
    "after_school": "After school",
    "all_day": "All day",
    "school_holiday_program": "School holiday program",
}

_ENVIRONMENT_LABELS: dict[str, str] = {
    "indoor": "Indoor",
    "outdoor": "Outdoor",
    "online": "Online",
    "at_home": "At home",
}

# Fields read and discarded. Named explicitly so the omission reads as a
# decision rather than an oversight.
_PERSONAL_FIELDS = ("contact_email", "contact_phone", "activity_contact_name")
_PERSONAL_FACILITY_FIELDS = ("facility_phone", "facility_email")

_SAFELINK_HOST = "safelinks.protection.outlook.com"

_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass
class TransformResult:
    programs: pd.DataFrame
    program_venues: pd.DataFrame
    organisations: pd.DataFrame
    program_access_needs: pd.DataFrame
    program_sports: pd.DataFrame
    venue_attributes: pd.DataFrame
    quarantine: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats
        lines = [
            "DS-09 transform",
            f"  activities read          {s.get('activities_read', 0):,}",
            f"  facilities read          {s.get('facilities_read', 0):,}",
            f"  organisations read       {s.get('organisations_read', 0):,}",
            f"  programs emitted         {len(self.programs):,}",
            f"  venues emitted           {len(self.program_venues):,}",
            f"    with a geocode         {s.get('venues_with_geocode', 0):,}",
            f"  access-need tags         {len(self.program_access_needs):,}",
            f"    programs carrying none {s.get('programs_untagged', 0):,}",
            f"  sport tags               {len(self.program_sports):,}",
            f"  venue attributes         {len(self.venue_attributes):,}",
            (
                f"  quarantined              {len(self.quarantine):,}"
                f"  ({s.get('quarantine_rate_pct', 0)}% of activities)"
            ),
        ]

        if len(self.quarantine):
            lines.append("  quarantine by reason")
            for reason, n in self.quarantine["reason"].value_counts().items():
                lines.append(f"    {reason:<24} {n:,}")

        unresolved = s.get("dangling", {})

        if any(unresolved.values()):
            lines.append("  references dropped to null")
            for label, n in unresolved.items():
                if n:
                    lines.append(f"    {label:<24} {n:,}")

        dropped = s.get("dropped", {})

        if dropped:
            lines.append("  read and discarded")
            for label, n in dropped.items():
                lines.append(f"    {label:<24} {n:,}")

        return "\n".join(lines)


# Helpers


def _clean(value: Any) -> str | None:
    """Clean a value and return None when it is empty."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    s = re.sub(r"\s+", " ", str(value)).strip()
    return s or None


def _text(value: Any) -> str | None:
    """Strip the HTML WordPress renders into content and title fields.

    Block markup, entities and non-breaking spaces all arrive inside `rendered`.
    Stored as text because it is displayed as provider prose, never parsed.
    """
    s = _clean(value)

    if s is None:
        return None

    s = re.sub(r"<br\s*/?>|</p>|</li>", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")

    return _clean(s)


def _rendered(value: Any) -> str | None:
    """WordPress wraps title and content as {'rendered': '...'}."""
    if isinstance(value, dict):
        return _text(value.get("rendered"))

    return _text(value)


def _published(value: Any) -> bool | None:
    """Apply the tri-state rule to a source boolean with no null state.

    True  -> the provider ticked the box, a published yes.
    False -> the provider did not tick the box. That is an ABSENCE OF
             INFORMATION, not a recorded absence, and it becomes None.

    DO NOT "fix" this to return False. The AAA Play facility record has no null
    state: facility_wheelchair_accessible is false on 230 of 552 venues, and on
    the data alone a false is indistinguishable from an empty form field.
    Returning False here would put a recorded absence on 230 venues on the
    strength of nobody having filled anything in. Same reasoning as DS-02.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    if isinstance(value, bool):
        return True if value else None

    s = str(value).strip().lower()

    if s in {"true", "t", "yes", "y", "1"}:
        return True

    return None


def _car_spaces(value: Any) -> int | None:
    """Accessible car space count.

    Unlike the booleans this field DOES have a null state: 169 facilities leave
    it empty while 86 record a literal 0. A provider who leaves it blank and a
    provider who types 0 have done different things, so 0 is kept as a recorded
    zero and only the blank becomes None. This is the exception to _published,
    and it exists because the data supports the distinction here and does not
    support it there.
    """
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return None

    number = _integer(value)

    return None if number is None or number < 0 else number


def _unwrap_safelink(url: Any) -> str | None:
    """Return the real target behind an Outlook safelink.

    Registration and social URLs arrive wrapped as
    kor01.safelinks.protection.outlook.com/?url=<percent-encoded target>.
    A safelink is tenant-scoped and will not resolve for every visitor, so the
    wrapper is removed and the target stored.
    """
    s = _clean(url)

    if s is None:
        return None

    parsed = urlparse(s)

    if _SAFELINK_HOST not in (parsed.netloc or "").lower():
        return s

    target = parse_qs(parsed.query).get("url", [None])[0]

    return _clean(unquote(target)) if target else None


def _number(value: Any) -> float | None:
    """Coerce one JSON scalar to a float, or None when it is not a number.

    Deliberately not pd.to_numeric. That function is typed for arrays and
    Series, so passing it a single value of unknown type fails mypy against
    every overload, and reaching for pandas to parse one field is overkill in
    any case. Behaviour matches errors="coerce": anything unparseable, empty or
    NaN comes back as None rather than raising.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return None if math.isnan(number) else number


def _integer(value: Any) -> int | None:
    """Coerce one JSON scalar to an int, or None. See _number."""
    number = _number(value)

    return None if number is None else int(number)


def _coordinate(value: Any) -> float | None:
    return _number(value)


def _reason_for_coordinates(lat: Any, lon: Any) -> str | None:
    """Check the coordinates and return a quarantine reason if needed.

    Kept in step with ds02._reason_for_coordinates. The two must agree.
    """
    lat_n = _number(lat)
    lon_n = _number(lon)

    if lat_n is None or lon_n is None:
        return "COORD_MISSING"

    if -90 <= lat_n <= 90 and -180 <= lon_n <= 180:
        return None

    if -90 <= lon_n <= 90 and -180 <= lat_n <= 180:
        return "COORD_TRANSPOSED"

    return "COORD_INVALID"


def _terms(
    raw_terms: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, dict[int, str]]:
    """Build taxonomy term id -> term name maps.

    About 25 zero-count junk terms sit in the lga taxonomy, bare lowercase
    council names such as "casey" and "kingston", plus one combined term naming
    two councils. They are mapped like any other term because scope is decided
    by point-in-polygon against DS-06, not by this taxonomy. The term travels as
    the publisher's own label and is never used as a boundary.
    """
    maps: dict[str, dict[int, str]] = {name: {} for name in TAXONOMIES}

    for taxonomy, terms in (raw_terms or {}).items():
        if taxonomy not in maps:
            continue

        for term in terms or []:
            term_id = _integer(term.get("id"))
            name = _rendered(term.get("name")) or _clean(term.get("name"))

            if term_id is not None and name:
                maps[taxonomy][term_id] = name

    return maps


def _term_names(ids: Any, lookup: dict[int, str]) -> list[str]:
    """Resolve a list of term ids, dropping any the taxonomy does not know."""
    if ids is None or isinstance(ids, float):
        return []

    if not isinstance(ids, (list, tuple)):
        ids = [ids]

    names: list[str] = []

    for raw_id in ids:
        term_id = _integer(raw_id)

        if term_id is None:
            continue

        name = lookup.get(term_id)

        if name and name not in names:
            names.append(name)

    return names


def _first_term(ids: Any, lookup: dict[int, str]) -> str | None:
    """Resolve a single term id to its name, or None.

    activity_lga and activity_region hold one id, not a list, and either may be
    null on a real record. Returning str | None here keeps that shape honest;
    the earlier version resolved a list, sliced it to one and padded it with
    None, which typed as list[str | None] and needed flattening afterwards.
    """
    names = _term_names(ids, lookup)

    return names[0] if names else None


def _weekdays(value: Any) -> list[str]:
    """Normalise the weekday list and order it Monday first."""
    if value is None or isinstance(value, float):
        return []

    if not isinstance(value, (list, tuple)):
        value = [value]

    found = {str(v).strip().lower() for v in value if _clean(v)}

    return [day for day in _WEEKDAYS if day in found]


def _string_list(value: Any) -> list[str]:
    if value is None or isinstance(value, float):
        return []

    if not isinstance(value, (list, tuple)):
        value = [value]

    out: list[str] = []

    for v in value:
        cleaned = _clean(v)

        if cleaned and cleaned not in out:
            out.append(cleaned)

    return out


def _label(slug: str, lookup: dict[str, str]) -> str:
    """Map a publisher slug to a display label, falling back to the slug.

    An unmapped slug is returned as-is rather than guessed at, so a new value
    upstream shows up on screen as an obviously unpolished string instead of
    being silently dropped.
    """
    return lookup.get(slug, slug)


def _slug_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _post_id(record: dict[str, Any]) -> int | None:
    return _integer(record.get("id"))


def _modified(record: dict[str, Any]) -> str | None:
    """Per-row publisher currency, which is what the freshness note reads."""
    return _clean(record.get("modified_gmt")) or _clean(record.get("modified"))


# Transform


def transform(
    activities: list[dict[str, Any]],
    facilities: list[dict[str, Any]],
    organisations: list[dict[str, Any]] | None = None,
    taxonomy_terms: dict[str, list[dict[str, Any]]] | None = None,
    load_run_id: int | None = None,
    retrieved_at: Any = None,
) -> TransformResult:
    """Convert the DS-09 post types into program, venue and link rows."""

    activities = activities or []
    facilities = facilities or []
    organisations = organisations or []

    stats: dict[str, Any] = {
        "activities_read": len(activities),
        "facilities_read": len(facilities),
        "organisations_read": len(organisations),
    }

    if not activities:
        raise ValueError(
            "DS-09 returned no activities. An empty collection is not a quiet "
            "week: the fetch writes no payload when nothing changed, so an "
            "empty list here means the pull failed and the load must not run."
        )

    terms = _terms(taxonomy_terms)

    # ---------------------------------------------------------------- venues

    venue_rows: list[dict[str, Any]] = []
    attribute_rows: list[dict[str, Any]] = []
    venues_with_geocode = 0

    for record in facilities:
        facility_id = _post_id(record)

        if facility_id is None:
            continue

        acf = record.get("acf") or {}
        location = acf.get("facility_location") or {}

        lat = _coordinate(location.get("lat"))
        lon = _coordinate(location.get("lng"))

        if lat is not None and lon is not None:
            venues_with_geocode += 1

        venue_rows.append(
            {
                "source_id": SOURCE_ID,
                "load_run_id": load_run_id,
                "program_venue_id": f"{SOURCE_ID}:facility:{facility_id}",
                "publisher_key": facility_id,
                "name": _rendered(record.get("title")),
                "full_address": _clean(location.get("address")),
                "suburb_name": _clean(location.get("city")) or _clean(location.get("suburb")),
                "postcode": _clean(location.get("post_code")) or _clean(location.get("postcode")),
                "latitude": lat,
                "longitude": lon,
                # Retained so the point can be re-derived from the address if
                # the Google provenance question closes against persisting it.
                "publisher_place_ref": _clean(location.get("place_id")),
                "accessible_car_spaces": _car_spaces(acf.get("facility_accessible_car_spaces")),
                "website_url": _unwrap_safelink(acf.get("facility_website")),
                "publisher_lga_label": _first_term(record.get("lga"), terms["lga"]),
                "source_url": _clean(record.get("link")),
                "publisher_last_updated": _modified(record),
                "retrieved_at": retrieved_at,
                # Set by the matcher, not here. This transformer never decides
                # whether two points are the same place. venue_matched is a
                # GENERATED column in the database and must not be emitted:
                # naming it in an INSERT is an error, and the point of
                # generating it is that it cannot disagree with venue_id.
                "venue_id": None,
                "match_distance_m": None,
                "match_name_similarity": None,
            }
        )

        for acf_field, label in _FACILITY_BOOLEANS.items():
            published = _published(acf.get(acf_field))

            # Only a published yes is emitted. A false produces no row at all,
            # which is how "no published information" is represented: absence of
            # a row, not a row saying no.
            if published:
                attribute_rows.append(
                    {
                        "source_id": SOURCE_ID,
                        "load_run_id": load_run_id,
                        "program_venue_id": f"{SOURCE_ID}:facility:{facility_id}",
                        "attribute_key": _slug_key(acf_field.removeprefix("facility_")),
                        "attribute_label": label,
                    }
                )

    # ---------------------------------------------------------- organisations

    org_rows: list[dict[str, Any]] = []

    for record in organisations:
        org_id = _post_id(record)

        if org_id is None:
            continue

        acf = record.get("acf") or {}

        org_rows.append(
            {
                "source_id": SOURCE_ID,
                "load_run_id": load_run_id,
                "organisation_id": f"{SOURCE_ID}:org:{org_id}",
                "publisher_key": org_id,
                "name": _rendered(record.get("title")),
                "website_url": _unwrap_safelink(acf.get("organisation_url")),
                "source_url": _clean(record.get("link")),
                "publisher_last_updated": _modified(record),
                "retrieved_at": retrieved_at,
            }
        )

    # -------------------------------------------------------------- programs

    program_rows: list[dict[str, Any]] = []
    access_need_rows: list[dict[str, Any]] = []
    sport_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []

    programs_untagged = 0
    dropped = {"personal contact fields": 0, "changing places claims": 0}
    dangling = {"facility reference": 0, "organisation reference": 0}

    facility_points = {
        row["publisher_key"]: (row["latitude"], row["longitude"]) for row in venue_rows
    }

    # Known keys, used to refuse a foreign key we cannot satisfy.
    #
    # WHY THIS EXISTS. The fetch pages three post types separately, six requests
    # for activities and six for facilities. A record unpublished between page 2
    # and page 5, or an organisation deleted while the pull is running, leaves an
    # activity pointing at an id that is not in the payload. Inserting that id
    # violates the foreign key and aborts the WHOLE load run, so one edit by one
    # provider mid-fetch would cost the week's programmes. The reference is
    # dropped to NULL and counted instead: the programme still displays, with one
    # less link on it, and the count surfaces in the run summary so a rising
    # number is visible rather than silent.
    known_facilities = {row["publisher_key"] for row in venue_rows}
    known_organisations = {row["publisher_key"] for row in org_rows}

    for record in facilities:
        if any(_clean((record.get("acf") or {}).get(f)) for f in _PERSONAL_FACILITY_FIELDS):
            dropped["personal contact fields"] += 1

        if (record.get("acf") or {}).get("facility_changing_places") in (
            True,
            "true",
            1,
            "1",
        ):
            dropped["changing places claims"] += 1

    for record in activities:
        activity_id = _post_id(record)

        if activity_id is None:
            continue

        acf = record.get("acf") or {}

        if any(_clean(acf.get(f)) for f in _PERSONAL_FIELDS):
            dropped["personal contact fields"] += 1

        facility_key = _integer(acf.get("activity_facility"))

        # The activity's own coordinates are often blank even where a facility
        # is linked, so the facility point is preferred and the activity point
        # is the fallback, never the other way round.
        lat, lon = facility_points.get(facility_key, (None, None))

        # The point survives even when the reference is dropped: a coordinate
        # read from a facility that existed at fetch time is still where the
        # programme runs.
        if lat is None or lon is None:
            lat = _coordinate(acf.get("activity_latitude"))
            lon = _coordinate(acf.get("activity_longitude"))

        reason = _reason_for_coordinates(lat, lon)

        if reason is not None:
            quarantine_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "natural_key": str(activity_id),
                    "reason": reason,
                    "detail": (
                        f"activity_facility={facility_key!r} latitude={lat!r} longitude={lon!r}"
                    ),
                    "payload": {
                        "activity_id": activity_id,
                        "title": _rendered(record.get("title")),
                        "link": _clean(record.get("link")),
                    },
                }
            )
            continue

        organisation_key = _integer(acf.get("activity_organisation"))

        if organisation_key is not None and organisation_key not in known_organisations:
            dangling["organisation reference"] += 1
            organisation_key = None

        if facility_key is not None and facility_key not in known_facilities:
            dangling["facility reference"] += 1
            facility_key = None

        weekdays = _weekdays(acf.get("weekday"))
        times_of_day = [
            _label(v, _TIME_OF_DAY_LABELS) for v in _string_list(acf.get("activity_when"))
        ]
        access_needs = _string_list(acf.get("activity_access_needs"))
        sports = _term_names(record.get("activity_type"), terms["activity_type"])

        if not access_needs:
            programs_untagged += 1

        price = _clean(acf.get("price"))

        program_rows.append(
            {
                "source_id": SOURCE_ID,
                "load_run_id": load_run_id,
                "program_id": f"{SOURCE_ID}:activity:{activity_id}",
                "publisher_key": activity_id,
                # Explicit rather than relying on the column default: _tuples
                # sends an explicit NULL for any column the frame lacks, and an
                # explicit NULL overrides a DEFAULT rather than falling back to
                # it.
                "kind": "program",
                "name": _rendered(record.get("title")),
                "description": _rendered(record.get("content")),
                # There is no start date, end date or season anywhere in this
                # post type. starts_at stays null and the API contract answers
                # a date-range filter with the recurrence block instead. Do not
                # synthesise a date from the weekday to make a filter work.
                "starts_at": None,
                "ends_at": None,
                "recurrence_weekdays": weekdays,
                "recurrence_time_of_day": times_of_day,
                "is_free": None if price is None else price.lower() == "free",
                "price_label": price,
                "age_ranges": _term_names(record.get("age_range"), terms["age_range"]),
                "welcoming": _string_list(acf.get("activity_welcoming")),
                "environment": [
                    _label(v, _ENVIRONMENT_LABELS)
                    for v in _string_list(acf.get("activity_environment"))
                ],
                "program_venue_id": (
                    f"{SOURCE_ID}:facility:{facility_key}" if facility_key is not None else None
                ),
                "organisation_id": (
                    f"{SOURCE_ID}:org:{organisation_key}" if organisation_key is not None else None
                ),
                "latitude": lat,
                "longitude": lon,
                "publisher_lga_label": _first_term(acf.get("activity_lga"), terms["lga"]),
                "publisher_region_label": _first_term(acf.get("activity_region"), terms["region"]),
                "registration_url": _unwrap_safelink(acf.get("registration_url")),
                "source_url": _clean(record.get("link")),
                "publisher_last_updated": _modified(record),
                "retrieved_at": retrieved_at,
            }
        )

        # An empty access-needs list emits no rows. Empty means the provider did
        # not say which needs are catered for; it does NOT mean the program
        # excludes anyone. Every one of these 530 listings is an accessible
        # sport program, which is the stated purpose of the service. The site's
        # own wheelchair basketball program carries an empty list. This table is
        # a refinement filter and must never be the predicate that builds the
        # events list.
        for need in access_needs:
            access_need_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "program_id": f"{SOURCE_ID}:activity:{activity_id}",
                    "access_need_key": _slug_key(need),
                    "access_need_label": _label(need, _ACCESS_NEED_LABELS),
                }
            )

        for sport in sports:
            sport_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "program_id": f"{SOURCE_ID}:activity:{activity_id}",
                    "sport_key": _slug_key(sport),
                    "sport_label": sport,
                }
            )

    programs = pd.DataFrame(program_rows)
    program_venues = pd.DataFrame(venue_rows)
    orgs = pd.DataFrame(org_rows)
    program_access_needs = pd.DataFrame(access_need_rows)
    program_sports = pd.DataFrame(sport_rows)
    venue_attributes = pd.DataFrame(attribute_rows)
    quarantine = pd.DataFrame(quarantine_rows)

    read = stats["activities_read"] or 1

    stats["venues_with_geocode"] = venues_with_geocode
    stats["programs_untagged"] = programs_untagged
    stats["dropped"] = dropped
    stats["dangling"] = dangling
    stats["quarantine_rate_pct"] = round(100 * len(quarantine) / read, 2)

    # Check that the generated IDs are still unique.
    for frame, column in (
        (programs, "program_id"),
        (program_venues, "program_venue_id"),
        (orgs, "organisation_id"),
    ):
        if len(frame):
            duplicates = int(frame[column].duplicated().sum())

            if duplicates:
                raise ValueError(
                    f"DS-09 produced {duplicates} duplicate {column} values, "
                    "which would break the idempotent upsert."
                )

    return TransformResult(
        programs=programs,
        program_venues=program_venues,
        organisations=orgs,
        program_access_needs=program_access_needs,
        program_sports=program_sports,
        venue_attributes=venue_attributes,
        quarantine=quarantine,
        stats=stats,
    )
