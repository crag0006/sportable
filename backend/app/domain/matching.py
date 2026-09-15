"""How a DS-09 place was matched to a DS-01 venue.

The loader stores the evidence (``program_venue.match_distance_m`` and
``match_name_similarity``), never the verdict, so the thresholds can move
without a reload. This is the same rule as ``data/derive/venue_match.py``;
the two must be changed together.
"""

NAME_AND_DISTANCE_M = 150
DISTANCE_ONLY_M = 25
NAME_ONLY_M = 400
MIN_SIMILARITY = 0.3
STRONG_SIMILARITY = 0.6


def match_basis(distance_m: float | None, similarity: float | None) -> str:
    if distance_m is None or similarity is None:
        return "none"
    if distance_m <= NAME_AND_DISTANCE_M and similarity > MIN_SIMILARITY:
        return "name_and_distance"
    if distance_m <= DISTANCE_ONLY_M:
        return "distance_only"
    if similarity >= STRONG_SIMILARITY and distance_m <= NAME_ONLY_M:
        return "name_only"
    return "none"
