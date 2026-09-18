"""Response models for the map legend (US3.1).

The legend is served as data rather than drawn from CSS so that the thing the
map renders and the thing a screen reader announces are provably the same
record. Every field here comes from one row of ``app.domain.legend.LEGEND``,
which mirrors the ``facility_legend`` view in
``data/sql/011_vocabulary_and_summary.sql``.
"""

from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Kind


class FacilityTypeOut(BaseModel):
    """§ one marker type. Three independent channels, as AC3.1.2 requires."""

    type: Kind
    label: str
    # The primary channel (AC3.1.3): the map stays readable in greyscale
    # because the shapes differ, not because the colours do.
    shape: Literal["circle", "square", "triangle", "diamond"]
    colour_token: str
    colour_hex: str
    description: str
    # AC3.1.4. The same row's wording, spoken.
    screen_reader_text: str


class FacilityTypesOut(BaseModel):
    heading: str
    facility_types: list[FacilityTypeOut]
    note: str
    # The whole legend as one block of speech, assembled from the
    # ``screen_reader_text`` values above and nothing else.
    screen_reader_summary: str
