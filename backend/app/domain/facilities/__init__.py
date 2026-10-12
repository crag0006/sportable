"""Facility vocabulary and rules, one package, four concerns.

- ``vocabulary``  kinds, keys, labels, aliases, parsing
- ``rules``       the six presentations and their fixed sentences (v0.2 §2.2)
- ``grouping``    matched / undocumented / not_available (v0.2 §4)
- ``legacy``      the v0.1 four-state view, until the frontend switches

The public names are re-exported here so callers import one place.
"""

from app.domain.facilities.grouping import Groups, Verdict, group, verdict
from app.domain.facilities.legacy import (
    AmenityView,
    Partition,
    State,
    classify,
    partition,
    rows_by_key,
    to_view,
    views_for,
)
from app.domain.facilities.rules import (
    NO_INFORMATION,
    Presentation,
    display,
    effective_status,
    message,
    present,
    presentations_for,
    rows_by_kind,
    within_limit,
)
from app.domain.facilities.vocabulary import (
    FRONTEND_KEYS,
    KEY_ALIASES,
    KEY_TO_KIND,
    KIND_LABELS,
    KIND_TO_KEY,
    KINDS,
    Display,
    FrontendKey,
    Kind,
    Status,
    parse_kinds,
    parse_needs,
)

__all__ = [
    "FRONTEND_KEYS",
    "KEY_ALIASES",
    "KEY_TO_KIND",
    "KINDS",
    "KIND_LABELS",
    "KIND_TO_KEY",
    "NO_INFORMATION",
    "AmenityView",
    "Display",
    "FrontendKey",
    "Groups",
    "Kind",
    "Partition",
    "Presentation",
    "State",
    "Status",
    "Verdict",
    "classify",
    "display",
    "effective_status",
    "group",
    "message",
    "parse_kinds",
    "parse_needs",
    "partition",
    "present",
    "presentations_for",
    "rows_by_key",
    "rows_by_kind",
    "to_view",
    "verdict",
    "views_for",
    "within_limit",
]
