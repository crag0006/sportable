"""Query parameter declarations, shared by the routers.

These exist for Swagger: the description and example beside each parameter.
The values are parsed by ``app.api.params`` from the raw request, so a
parameter spelled an old way (``limit`` for ``distance_m``) still works.
"""

from typing import Annotated

from fastapi import Query

SportQ = Annotated[str, Query(description="A sport name from /sports.", examples=["Basketball"])]
SportsQ = Annotated[
    str | None, Query(description="A name from /sports or /events/sports; comma list allowed.")
]
SuburbQ = Annotated[
    str | None,
    Query(description='Suburb, with or without a postcode: "Preston 3072". Alias: place.'),
]
PostcodeQ = Annotated[
    str | None, Query(description="Four-digit postcode. Give suburb, postcode or near.")
]
NearQ = Annotated[
    str | None,
    Query(description='"lat,lon" from browser geolocation. Give suburb, postcode or near.'),
]
FacilitiesQ = Annotated[
    list[str] | None,
    Query(
        description="Access requirements: comma list of accessible_toilet, "
        "accessible_parking, accessible_transport_stop, accessible_change_facility. "
        "Aliases: needs, types, amenities, or flag style toilet=true. Groups; never hides."
    ),
]
# Declared as text, not int, so a value such as ``abc`` or ``500.5`` reaches
# ``parse_band`` and is answered as ``invalid_distance_band`` (contract §10)
# rather than by FastAPI's own integer check.
DistanceQ = Annotated[
    str | None,
    Query(
        description="Facility distance limit in metres, one of the bands in /config. "
        "Aliases: limit, within.",
        examples=["500"],
    ),
]
FromQ = Annotated[
    str | None,
    Query(
        alias="from",
        description='Optional starting point: "Preston 3072", "3072" or "lat,lon". '
        "Adds distance_m and reference_point to the page.",
    ),
]
OriginQ = Annotated[
    str,
    Query(
        alias="from",
        description='Starting point: "Preston 3072", "3072" or "lat,lon". '
        "Required, there is no default origin (AC2.2.1).",
    ),
]
OptionalOriginQ = Annotated[
    str | None,
    Query(
        alias="from",
        description='Starting point: "Preston 3072", "3072" or "lat,lon". '
        "Required when the event has a matched venue; there is no default origin (AC2.2.1).",
    ),
]
WithinQ = Annotated[
    str | None,
    Query(
        description="Corridor half-width in metres, one of the bands in /config. "
        "Default corridor_default_m.",
        examples=["400"],
    ),
]
TypesQ = Annotated[
    str | None,
    Query(
        description="Comma list of facility types. "
        "Default: accessible_toilet, accessible_parking, accessible_transport_stop."
    ),
]
TypeaheadQ = Annotated[
    str | None, Query(description="Optional typeahead filter, case-insensitive.", examples=["net"])
]
ResolveQ = Annotated[
    str,
    Query(
        description='A suburb ("Preston"), suburb and postcode ("Preston 3072"), '
        'a postcode ("3072") or "lat,lon".',
        examples=["Preston 3072"],
    ),
]

# ------------------------------------------------------------------ events
DateFromQ = Annotated[
    str | None, Query(alias="from", description="YYYY-MM-DD, local date, inclusive. Default today.")
]
DateToQ = Annotated[
    str | None, Query(description="YYYY-MM-DD, inclusive. Default from + default_window_days.")
]
WithinMQ = Annotated[
    int | None, Query(description="Radius around the place, metres. Default 10000.")
]
VenueIdQ = Annotated[str | None, Query(description="Events at one venue.")]
StatusQ = Annotated[
    str | None, Query(description="listable (default) or all.", examples=["listable"])
]
IncludePastQ = Annotated[
    bool | None, Query(description="Also fixtures already started inside the window.")
]
WeekdayQ = Annotated[
    str | None, Query(description="Programs on these weekdays, comma list, e.g. saturday.")
]
TimeOfDayQ = Annotated[
    str | None, Query(description="morning, afternoon, evening, after_school; comma list.")
]
PriceQ = Annotated[str | None, Query(description="free or paid.")]
PageQ = Annotated[int | None, Query(description="1-based.")]
IdsQ = Annotated[
    str | None,
    Query(
        description="Comma list of event ids, at most 50: these events in request order, whatever "
        "their status; the other filters are ignored and `missing` lists ids that no longer exist."
    ),
]
PageSizeQ = Annotated[int | None, Query(description="Default from /config, max 200.")]
