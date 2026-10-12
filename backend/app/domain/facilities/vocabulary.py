"""The facility vocabulary: database kinds, frontend keys, labels and aliases.

One spelling per facility, product-wide. The four kinds are the
``amenity_kind`` enum; the labels are what every tile, legend row and spoken
sentence uses; the keys and aliases are what a client may send.
"""

from collections.abc import Iterable
from typing import Literal

FrontendKey = Literal["toilet", "parking", "stop", "change"]
FRONTEND_KEYS: tuple[FrontendKey, ...] = ("toilet", "parking", "stop", "change")

KIND_TO_KEY: dict[str, FrontendKey] = {
    "accessible_toilet": "toilet",
    "accessible_parking": "parking",
    "accessible_transport_stop": "stop",
    "accessible_change_facility": "change",
}

KEY_TO_KIND: dict[FrontendKey, str] = {key: kind for kind, key in KIND_TO_KEY.items()}

# Everything a client might reasonably send for a facility filter.
KEY_ALIASES: dict[str, FrontendKey] = {
    "toilet": "toilet",
    "toilets": "toilet",
    "accessible_toilet": "toilet",
    "parking": "parking",
    "accessible_parking": "parking",
    "stop": "stop",
    "stops": "stop",
    "transport": "stop",
    "accessible_transport_stop": "stop",
    "step_free_transport_stop": "stop",
    "change": "change",
    "changing": "change",
    "change_facility": "change",
    "accessible_change_facility": "change",
}

Kind = Literal[
    "accessible_toilet",
    "accessible_parking",
    "accessible_transport_stop",
    "accessible_change_facility",
]
KINDS: tuple[Kind, ...] = (
    "accessible_toilet",
    "accessible_parking",
    "accessible_transport_stop",
    "accessible_change_facility",
)

# Transport is labelled as what the data actually confirms: only railway
# stations publish wheelchair_boarding (Data Layer guide §2.3).
KIND_LABELS: dict[str, str] = {
    "accessible_toilet": "Accessible toilet",
    "accessible_parking": "Accessible parking",
    "accessible_transport_stop": "Step-free railway station",
    "accessible_change_facility": "Accessible change facility",
}

Status = Literal["confirmed", "not_available", "no_published_information"]
Display = Literal[
    "at_venue",
    "nearby",
    "beyond_limit",
    "not_available",
    "not_available_alternative",
    "no_published_information",
]


def parse_needs(values: Iterable[str]) -> list[FrontendKey]:
    """Accept ``toilet,parking``, repeated params, or any of the known aliases.

    Raises ValueError naming the first token that is not a facility.
    """
    needs: list[FrontendKey] = []
    for raw in values:
        for token in raw.split(","):
            name = token.strip().lower()
            if not name:
                continue
            key = KEY_ALIASES.get(name)
            if key is None:
                raise ValueError(name)
            if key not in needs:
                needs.append(key)
    return needs


def parse_kinds(values: Iterable[str]) -> list[str]:
    """Like ``parse_needs`` but returns database kinds, in request order."""
    return [KEY_TO_KIND[key] for key in parse_needs(values)]
