"""Contract v0.2 shapes over HTTP, against the in-memory repository.

The key-set checks are the "contract snapshot": a field added to or removed
from a response without updating API_CONTRACT_v0.2.md fails here first.
"""

from fastapi.testclient import TestClient

SEARCH = "/api/v1/venues/search"

FACILITY_KEYS = {
    "type",
    "label",
    "status",
    "basis",
    "display",
    "distance_limit_m",
    "message",
}
SEARCH_KEYS = {
    "sport",
    "reference_point",
    "distance_limit_m",
    "search_radius_m",
    "facilities_requested",
    "counts",
    "results",
    "undocumented_group",
    "not_available_group",
    "retrieved_at",
    # v0.1, until the freeze
    "place",
    "total",
    "matched",
    "undocumented",
    "not_available",
}
CARD_KEYS = {
    "id",
    "name",
    "address",
    "suburb",
    "postcode",
    "lga",
    "latitude",
    "longitude",
    "sports",
    "surface_types",
    "href",
    "facilities",
    "access_chain",
    "limits",
    "sources",
    "upcoming_events",
    # US3.3 - the Read Aloud payload. Part of the page's own shape, not an
    # add-on: see tests/unit/test_summary.py for what it must contain.
    "summary_sentences",
    "last_updated",
    # v0.1, until the freeze
    "lat",
    "lon",
    "surface",
    "amenities",
    "unpublished",
}


# ------------------------------------------------------------------ config
def test_config_carries_the_v02_defaults(client: TestClient):
    body = client.get("/api/v1/config").json()
    assert body["corridor_default_m"] == 400
    assert body["default_stale_after_days"] == 365
    assert body["events"] == {"default_window_days": 28, "max_window_days": 92, "page_size": 50}
    assert body["timezone"] == "Australia/Melbourne"


def test_sports_are_objects_with_counts_and_take_a_filter(client: TestClient):
    body = client.get("/api/v1/sports", params={"q": "net"}).json()
    assert body["sports"] == [{"name": "Netball", "venue_count": 1, "event_count": 0}]


# ------------------------------------------------------------------ search
def test_search_v02_shape(client: TestClient):
    body = client.get(SEARCH, params={"sport": "Basketball", "suburb": "Preston 3072"}).json()
    assert set(body) == SEARCH_KEYS
    assert body["sport"] == "Basketball"
    assert body["reference_point"]["kind"] == "suburb"
    assert body["reference_point"]["code"] == "SAL21713"
    assert body["counts"] == {
        "total_for_sport": 3,
        "matched": 3,
        "undocumented": 0,
        "not_available": 0,
    }
    assert body["results"] == body["matched"]  # compat: same objects
    venue = body["results"][0]
    assert venue["href"] == "/venues/10432"
    assert venue["distance_m"] == 640 and venue["distance"] == 0.6
    assert venue["surface_types"] == ["Indoor sprung timber"]
    assert [f["type"] for f in venue["facilities"]] == [
        "accessible_toilet",
        "accessible_parking",
        "accessible_transport_stop",
        "accessible_change_facility",
    ]
    for tile in venue["facilities"]:
        assert set(tile) >= FACILITY_KEYS


def test_search_tiles_are_evaluated_at_the_requested_band(client: TestClient):
    at_1000 = client.get(
        SEARCH, params={"sport": "Basketball", "suburb": "Preston", "distance_m": 1000}
    ).json()
    at_250 = client.get(
        SEARCH, params={"sport": "Basketball", "suburb": "Preston", "distance_m": 250}
    ).json()
    # Reservoir's station is 540 m away: confirmed at 1000, beyond the limit at 250.
    stop_1000 = at_1000["results"][2]["facilities"][2]
    stop_250 = at_250["results"][2]["facilities"][2]
    assert stop_1000["status"] == "confirmed" and stop_1000["display"] == "nearby"
    assert stop_250["status"] == "no_published_information"
    assert stop_250["display"] == "beyond_limit"
    assert stop_250["distance_m"] == 540 and stop_250["distance_limit_m"] == 250
    assert "beyond your 250 m limit" in stop_250["message"]


def test_search_groups_list_recorded_absences(client: TestClient):
    body = client.get(
        SEARCH,
        params={
            "sport": "Basketball",
            "suburb": "Preston",
            "facilities": "accessible_toilet,accessible_change_facility",
        },
    ).json()
    assert body["facilities_requested"] == ["accessible_toilet", "accessible_change_facility"]
    assert [v["id"] for v in body["results"]] == ["11876"]
    assert [v["id"] for v in body["undocumented_group"]["results"]] == ["10432"]
    assert body["undocumented_group"]["label"] == (
        "1 more venue have no published information about "
        "accessible toilet or accessible change facility"
    )
    # v0.1 only counted these; v0.2 lists them so the alternative can be shown.
    assert [v["id"] for v in body["not_available_group"]["results"]] == ["10088"]
    assert body["counts"]["not_available"] == 1 and body["not_available"] == 1
    toilet = body["not_available_group"]["results"][0]["facilities"][0]
    assert toilet["display"] == "not_available_alternative"
    assert toilet["alternative"]["name"] == "Edwardes Lake Park toilets"
    assert toilet["alternative"]["distance_m"] == 158
    assert toilet["alternative"]["source"]["id"] == "DS-02"


def test_search_near_a_point(client: TestClient):
    body = client.get(SEARCH, params={"sport": "Basketball", "near": "-37.7412,145.0006"}).json()
    assert body["reference_point"] == {
        "label": "your starting point",
        "kind": "point",
        "latitude": -37.7412,
        "longitude": 145.0006,
    }


def test_search_outside_coverage_is_its_own_error(client: TestClient):
    response = client.get(SEARCH, params={"sport": "Basketball", "suburb": "Hobart"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "outside_coverage"


def test_unknown_place_suggests(client: TestClient):
    response = client.get(SEARCH, params={"sport": "Basketball", "suburb": "Prestn"})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "unknown_place"
    assert "Preston 3072" in body["message"]


def test_provenance_on_every_confirmed_tile(client: TestClient):
    body = client.get(SEARCH, params={"sport": "Basketball", "suburb": "Preston"}).json()
    for venue in body["results"]:
        for tile in venue["facilities"]:
            if tile["status"] == "confirmed":
                source = tile["source"]
                assert source["name"] and "possibly_out_of_date" in source
                assert source["stale_after_days"] == 365


# -------------------------------------------------------------- venue page
def test_venue_card_v02_shape(client: TestClient):
    body = client.get("/api/v1/venues/10432").json()
    assert set(body) == CARD_KEYS
    assert body["href"] == "/venues/10432"
    assert [link["link"] for link in body["access_chain"]] == [
        "arrive_parking",
        "arrive_transport",
        "enter",
        "toilet",
        "change",
        "play",
    ]
    enter = body["access_chain"][2]
    assert enter.get("facility_type") is None and enter["summary"] == "Not published."
    assert body["limits"]["heading"] == "What this page cannot tell you"
    assert len(body["limits"]["items"]) == 4
    assert body["upcoming_events"]["count"] == 1
    assert body["upcoming_events"]["href"] == "/events?venue_id=10432"
    names = {s["name"] for s in body["sources"]}
    assert "National Public Toilet Map" in names


def test_venue_card_detail_and_attached_description(client: TestClient):
    body = client.get("/api/v1/venues/10432").json()
    toilet, parking = body["facilities"][0], body["facilities"][1]
    # Nearby public toilet: the amenity is the answer, so its detail is shown.
    assert toilet["display"] == "nearby"
    assert toilet["detail"]["name"] == "Preston City Oval Toilets"
    assert toilet["detail"]["location_relative_to_venue"] == "a separate public facility nearby"
    assert toilet["detail"]["key_required"] is True
    assert (toilet["detail"]["latitude"], toilet["detail"]["longitude"]) == (-37.7398, 145.0101)
    # Publisher-confirmed parking with a DS-04 description attached (007):
    # status from DS-01, detail from DS-04, both named, the bay's identity not.
    assert parking["display"] == "at_venue"
    assert parking["source"]["id"] == "DS-01"
    assert parking["detail"]["detail_source"]["id"] == "DS-04"
    assert parking["detail"]["detail_source"]["distance_m"] == 18
    assert parking["detail"]["opening_hours"] == "24 hours"
    assert "name" not in parking["detail"] or parking["detail"]["name"] is None


def test_venue_card_unrecorded_flags_are_statements(client: TestClient):
    body = client.get("/api/v1/venues/11876").json()
    toilet = body["facilities"][0]
    assert toilet["display"] == "nearby"
    assert toilet["detail"]["opening_hours_unrecorded"] is True
    assert toilet["detail"]["key_requirement_unrecorded"] is True


def test_venue_card_distance_in_metres_from_a_place(client: TestClient):
    body = client.get("/api/v1/venues/10432", params={"from": "Preston 3072"}).json()
    assert body["distance_m"] == 775 and body["distance"] == 0.8
    assert body["reference_point"]["label"] == "the centre of Preston 3072"


def test_venue_card_band_parameter(client: TestClient):
    body = client.get("/api/v1/venues/10088", params={"distance_m": 250}).json()
    stop = body["facilities"][2]
    assert stop["display"] == "beyond_limit" and stop["distance_limit_m"] == 250


def test_directions_is_reserved(client: TestClient):
    response = client.get("/api/v1/venues/10432/directions", params={"from": "3072"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_implemented"


# ---------------------------------------------------------------- corridor
def test_corridor_v02_fields(client: TestClient):
    body = client.get(
        "/api/v1/venues/10432/corridor", params={"from": "Preston 3072", "within": 1000}
    ).json()
    assert body["disclaimer"].startswith("This is a straight-line corridor, not a route.")
    assert body["venue"]["href"] == "/venues/10432"
    first = body["facilities"][0]
    assert first["key_required"] is False and first["mlak"] is False
    assert first["source"]["possibly_out_of_date"] in (True, False)
    change = client.get(
        "/api/v1/venues/10432/corridor", params={"from": "3072", "types": "change"}
    ).json()["types"][0]
    assert change["status"] == "none_within"
    assert (
        change["message"] == "No accessible change facilities recorded within 400 m of this line."
    )


# --------------------------------------------------------------- locations
def test_resolve_three_outcomes(client: TestClient):
    resolved = client.get("/api/v1/locations/resolve", params={"q": "Preston 3072"}).json()
    assert resolved["outcome"] == "resolved"
    assert resolved["reference_point"]["label"] == "the centre of Preston 3072"
    assert resolved["matched"] == {"label": "Preston", "kind": "suburb"}

    outside = client.get("/api/v1/locations/resolve", params={"q": "Hobart"}).json()
    assert outside["outcome"] == "outside_coverage"
    assert outside["coverage"]["examples"]
    assert "outside the area SportAble covers" in outside["message"]

    unresolved = client.get("/api/v1/locations/resolve", params={"q": "Prestn"}).json()
    assert unresolved["outcome"] == "unresolved"
    assert unresolved["suggestions"] == [
        {"label": "Preston 3072", "kind": "suburb", "code": "SAL21713"}
    ]


def test_resolve_accepts_coordinates(client: TestClient):
    body = client.get("/api/v1/locations/resolve", params={"q": "-37.8,144.96"}).json()
    assert body["outcome"] == "resolved" and body["matched"]["kind"] == "point"


# ----------------------------------------------------------------- sources
def test_sources_register(client: TestClient):
    body = client.get("/api/v1/sources").json()
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["DS-01"]["status"] == "loaded" and by_id["DS-01"]["row_count"] == 2153
    assert by_id["DS-01"]["licence"].startswith("Creative Commons Attribution 4.0")
    assert by_id["DS-01"]["feeds"] == ["venues", "accessible_toilet", "accessible_parking"]
    assert by_id["DS-02"]["possibly_out_of_date"] is True
    assert by_id["DS-05"]["status"] == "not_used" and by_id["DS-05"]["tier"] == "live"
    assert by_id["DS-05"]["note"]
