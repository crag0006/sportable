"""The map legend as data (US3.1).

THE ONE RULE — "the spoken legend and the drawn legend are the same row."

The legend used to be CSS. CSS can colour a marker but it cannot be asked what
the marker means, so nothing could check that the legend explained every marker
the map draws (AC3.1.1), and the screen-reader wording lived in a different
file from the visual wording and was free to drift (AC3.1.4). Here they are one
record, and the endpoint serves that record whole.

WHY SHAPE, NOT COLOUR, CARRIES THE MEANING
    AC3.1.3 requires the four types to stay distinguishable in greyscale.
    Colour alone fails that on a monochrome display, on a printout, on a
    washed-out projector, and for the several forms of colour vision
    deficiency. So ``shape`` is the primary channel — circle, square, triangle,
    diamond, four outlines that survive desaturation completely and stay apart
    at marker size — and ``colour_token`` repeats the same distinction for
    people who can use it. AC3.1.2 then asks for a text label as well, which is
    the third independent channel: ``display_label``.

WHY THE LABEL IS NOT DEFINED HERE
    ``display_label`` is ``KIND_LABELS`` from ``app.domain.facilities``, the
    same dictionary the four facility tiles are labelled from. A legend that
    spelled a facility differently from the tile beside it would be a legend
    the reader has to translate, so there is one spelling and this module
    borrows it rather than restating it.

WHERE THE MATCHING SQL LIVES
    ``data/sql/011_vocabulary_and_summary.sql`` creates ``facility_legend``,
    the same vocabulary as a view driven by ``unnest(enum_range(amenity_kind))``
    so a new marker type cannot exist without a legend row. This module is the
    copy the API serves: the legend is the enum, it changes only when a
    migration changes it, and a database round trip per page load would buy
    nothing. ``tests/unit/test_legend.py`` reads both files and fails if the
    enum, the SQL view and this tuple ever stop agreeing — that check is what
    makes "explains every icon" a property of the system rather than a promise.
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.facilities import KIND_LABELS, KINDS, Kind

# The four outlines. Deliberately not "pin", "star" or "cross": these four stay
# told apart at 16 px, in greyscale, and at the edge of the visual field.
Shape = Literal["circle", "square", "triangle", "diamond"]


@dataclass(frozen=True)
class LegendEntry:
    """One marker type: what it looks like, what it means, how it is spoken."""

    kind: Kind
    shape: Shape
    # The CSS custom property the frontend defines. A token rather than a
    # literal so the legend swatch and the marker itself cannot be given two
    # different colours by two different stylesheets.
    colour_token: str
    # What the token resolves to by default. Present so AC3.1.3 is checkable
    # rather than asserted — see test_legend.py, which desaturates these four
    # and fails if any pair converges. Markers are drawn with a dark stroke, so
    # contrast against a pale basemap comes from the outline and the fill is
    # free to span the luminance range.
    colour_hex: str
    description: str
    # AC3.1.4. The spoken form, on the same record as the drawn form. Shape is
    # named before colour because shape is what the reader is being told to
    # look for.
    screen_reader_text: str

    @property
    def display_label(self) -> str:
        return KIND_LABELS[self.kind]


LEGEND: tuple[LegendEntry, ...] = (
    LegendEntry(
        kind="accessible_toilet",
        shape="circle",
        colour_token="--facility-toilet",
        colour_hex="#0B3D66",
        description=(
            "A toilet with wheelchair access, either at the venue or a separate "
            "public toilet nearby."
        ),
        screen_reader_text="Accessible toilet: a circle, dark blue.",
    ),
    LegendEntry(
        kind="accessible_parking",
        shape="square",
        colour_token="--facility-parking",
        colour_hex="#B3541E",
        description="An accessible parking bay, either at the venue or on a nearby street.",
        screen_reader_text="Accessible parking: a square, burnt orange.",
    ),
    LegendEntry(
        kind="accessible_transport_stop",
        shape="triangle",
        colour_token="--facility-transport",
        colour_hex="#7A9E3F",
        description="A railway station the operator records as step-free.",
        screen_reader_text="Step-free railway station: a triangle, olive green.",
    ),
    LegendEntry(
        kind="accessible_change_facility",
        shape="diamond",
        colour_token="--facility-change",
        colour_hex="#F2C744",
        description=(
            "An accessible change facility, which may or may not be an accredited "
            "Changing Places room."
        ),
        screen_reader_text="Accessible change facility: a diamond, gold.",
    ),
)

LEGEND_HEADING = "What the map markers mean"

# AC3.1.3 again, said out loud rather than left for the reader to infer. This
# sentence is why the shapes exist, so it ships with them.
LEGEND_NOTE = (
    "Each facility type has its own shape as well as its own colour, so the map "
    "can be read without relying on colour."
)


def screen_reader_summary() -> str:
    """AC3.1.4 - the whole legend as one block of speech.

    Assembled from ``screen_reader_text`` and nothing else, so a marker cannot
    be described in the spoken legend unless it is also in the drawn one, and
    cannot be renamed in one without being renamed in the other.
    """
    spoken = " ".join(entry.screen_reader_text for entry in LEGEND)
    return f"{LEGEND_HEADING}. {spoken} {LEGEND_NOTE}"


def legend_kinds() -> tuple[str, ...]:
    """The kinds the legend covers, in declaration order."""
    return tuple(entry.kind for entry in LEGEND)


# A guard that runs at import rather than only under pytest: the API refuses to
# start with a marker type it cannot explain, which is a louder failure than a
# map that quietly draws an unlabelled pin.
if legend_kinds() != KINDS:  # pragma: no cover - the assertion is the product
    raise RuntimeError(
        "facility legend and amenity_kind have diverged: "
        f"legend={legend_kinds()} kinds={KINDS}. "
        "Every marker the map can draw must have a legend entry (AC3.1.1)."
    )
