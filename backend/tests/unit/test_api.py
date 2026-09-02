"""HTTP-level tests against the in-memory repository."""

import json

from fastapi.testclient import TestClient

SEARCH = "/api/v1/search"


# ------------------------------------------------------------------ basics
def test_health(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_config_falls_back_without_env(client: TestClient):
    body = client.get("/api/v1/config").json()
    assert body["distance_bands_m"] == [250, 500, 1000]
    assert body["default_distance_m"] in body["distance_bands_m"]
    assert body["source"] == "fallback"


def test_unknown_route_is_json_404(client: TestClient):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_sports_on_both_paths(client: TestClient):
    for path in ("/api/v1/sports", "/api/v1/meta/sports"):
        assert client.get(path).json()["sports"] == ["Basketball", "Netball", "Swimming"]


def test_suburbs_carry_the_display_label(client: TestClient):
    body = client.get("/api/v1/suburbs").json()
    assert {"suburb": "Preston", "postcode": "3072", "label": "Preston 3072"} in body["suburbs"]


# ------------------------------------------------------------------ search
def test_search_returns_the_frontend_wrapper(client: TestClient):
    body = client.get(SEARCH, params={"sport": "Basketball", "suburb": "Preston 3072"}).json()
    assert set(body) >= {"place", "total", "matched", "undocumented"}
    assert body["place"] == "Preston 3072"
    assert body["total"] == 3
    assert body["reference_point"]["label"] == "the centre of Preston 3072"
    assert [v["id"] for v in body["matched"]] == ["10432", "11876", "10088"]
    assert body["undocumented"] == []


def test_venue_shape_matches_the_mock(client: TestClient):
    body = client.get(SEARCH, params={"sport": "Basketball", "postcode": "3072"}).json()
    venue = body["matched"][0]
    assert venue["id"] == "10432"
    assert venue["distance"] == 0.6  # kilometres
    assert venue["sports"] == ["Basketball", "Netball"]
    assert venue["surface"] == "Indoor sprung timber"
    assert list(venue["amenities"]) == ["toilet", "parking", "stop", "change"]
    assert venue["amenities"]["toilet"] == {"state": "recorded", "distance": 45}
    assert venue["amenities"]["parking"] == {"state": "confirmed"}
    assert venue["amenities"]["stop"] == {"state": "none"}
    assert venue["amenities"]["change"] == {"state": "recorded", "distance": 1340}


def test_filter_groups_undocumented_and_counts_not_available(client: TestClient):
    body = client.get(
        SEARCH, params={"sport": "Basketball", "suburb": "Preston", "needs": "toilet,change"}
    ).json()
    assert [v["id"] for v in body["matched"]] == ["11876"]
    assert [v["id"] for v in body["undocumented"]] == ["10432"]
    assert body["not_available"] == 1
    assert body["total"] == 3


def test_filter_accepts_flag_style_and_limit(client: TestClient):
    body = client.get(
        SEARCH, params={"sport": "Basketball", "suburb": "Preston", "stop": "true", "limit": 250}
    ).json()
    assert body["distance_limit_m"] == 250
    # Northcote's stop is 210 m: passes. Preston: none. Reservoir: 540 m, beyond.
    assert [v["id"] for v in body["matched"]] == ["11876"]
    assert [v["id"] for v in body["undocumented"]] == ["10432", "10088"]


def test_invalid_band_is_422(client: TestClient):
    response = client.get(SEARCH, params={"sport": "Basketball", "suburb": "Preston", "limit": 300})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_distance_band"


def test_missing_sport_is_422(client: TestClient):
    response = client.get(SEARCH, params={"suburb": "Preston"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_place_is_422(client: TestClient):
    response = client.get(SEARCH, params={"sport": "Basketball", "suburb": "Atlantis"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_place"


def test_unknown_facility_is_422(client: TestClient):
    response = client.get(
        SEARCH, params={"sport": "Basketball", "suburb": "Preston", "needs": "lift"}
    )
    assert response.status_code == 422


def test_no_combined_score_anywhere(client: TestClient):
    forbidden = ("score", "rating", "percentage", "stars", "overall")
    for path, params in (
        (SEARCH, {"sport": "Basketball", "suburb": "Preston"}),
        ("/api/v1/venues/10432", {}),
    ):
        raw = json.dumps(client.get(path, params=params).json()).lower()
        for word in forbidden:
            assert word not in raw, f"{word!r} appears in {path}"


# ------------------------------------------------------------- venue card
def test_venue_card(client: TestClient):
    body = client.get("/api/v1/venues/10432").json()
    assert body["name"] == "Preston City Oval"
    assert body["lga"] == "Darebin"
    toilet = body["amenities"]["toilet"]
    assert toilet["state"] == "recorded"
    assert toilet["location"] == "public_nearby"
    assert toilet["opening_hours"] == "6:00am - 9:00pm"
    assert toilet["mlak"] is True
    assert toilet["source"]["name"] == "National Public Toilet Map"
    assert toilet["source"]["published_at"] == "2026-07-14"
    assert (toilet["lat"], toilet["lon"]) == (-37.7398, 145.0101)  # pin for the map
    parking = body["amenities"]["parking"]
    assert parking["state"] == "confirmed"
    assert parking["location"] == "at_venue"
    assert "distance" not in parking
    assert "name" not in parking and "opening_hours" not in parking  # the nearby bay's, not ours
    assert "lat" not in parking and "lon" not in parking  # likewise: not the venue's position
    assert parking["source"]["name"] == "Sport and Recreation Victoria facilities list"
    assert body["amenities"]["stop"] == {"state": "none"}
    change = body["amenities"]["change"]
    assert change["state"] == "recorded" and "lat" not in change  # no position recorded


def test_venue_card_always_names_what_it_cannot_tell_you(client: TestClient):
    body = client.get("/api/v1/venues/11876").json()  # no chain rows in the fake
    assert [u["key"] for u in body["unpublished"]] == ["enter", "play"]
    assert all(u["reason"] for u in body["unpublished"])


def test_venue_card_uses_the_chain_detail_when_present(client: TestClient):
    body = client.get("/api/v1/venues/10432").json()
    assert body["unpublished"][0]["reason"] == "Not published."


def test_missing_venue_is_404(client: TestClient):
    response = client.get("/api/v1/venues/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "venue_not_found"


# ------------------------------------------------------- venue card ?from=
def test_venue_card_without_from_has_no_distance(client: TestClient):
    body = client.get("/api/v1/venues/10432").json()
    assert "distance" not in body and "reference_point" not in body


def test_venue_card_distance_from_a_place(client: TestClient):
    body = client.get("/api/v1/venues/10432", params={"from": "Preston 3072"}).json()
    assert body["reference_point"]["label"] == "the centre of Preston 3072"
    assert body["distance"] == 0.8  # ~775 m from the fake's Preston point


def test_venue_card_distance_from_coordinates(client: TestClient):
    # The venue's own position: a lat,lon pair is used as-is, no lookup.
    body = client.get("/api/v1/venues/10432", params={"from": "-37.7401,145.0093"}).json()
    assert body["distance"] == 0.0
    assert body["reference_point"]["label"] == "your starting point"


def test_venue_card_rejects_an_unknown_starting_point(client: TestClient):
    response = client.get("/api/v1/venues/10432", params={"from": "Hobart 7000"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_place"


def test_venue_card_rejects_impossible_coordinates(client: TestClient):
    response = client.get("/api/v1/venues/10432", params={"from": "-97.0,145.0"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------- corridor
CORRIDOR = "/api/v1/venues/10432/corridor"


def test_corridor_requires_a_starting_point(client: TestClient):
    response = client.get(CORRIDOR)
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert "from" in body["message"]


def test_corridor_lists_facilities_in_travel_order(client: TestClient):
    body = client.get(CORRIDOR, params={"from": "Preston 3072", "within": "500"}).json()
    assert body["venue"]["id"] == "10432"
    assert body["origin"]["label"] == "the centre of Preston 3072"
    assert body["path"]["kind"] == "straight_line"
    assert body["path"]["within_m"] == 500
    assert len(body["path"]["coordinates"]) == 2
    assert [f["seq"] for f in body["facilities"]] == [1, 2]
    assert [f["type"] for f in body["facilities"]] == ["toilet", "parking"]  # by fraction
    first = body["facilities"][0]
    assert first["distance_from_path_m"] == 90
    assert first["along_path_m"] == round(0.2 * body["path"]["length_m"])
    assert first["mlak"] is False
    assert first["source"]["name"] == "National Public Toilet Map"


def test_corridor_widening_the_band_reveals_the_far_toilet(client: TestClient):
    body = client.get(CORRIDOR, params={"from": "Preston 3072", "within": "1000"}).json()
    names = [f["name"] for f in body["facilities"]]
    assert names == ["Gower St toilets", "High St bay", "Northland"]
    toilet = next(t for t in body["types"] if t["type"] == "toilet")
    assert toilet == {
        "type": "toilet",
        "label": "Accessible toilets",
        "count": 2,
        "status": "found",
    }


def test_corridor_separates_none_within_from_no_data(client: TestClient):
    body = client.get(CORRIDOR, params={"from": "3072", "types": "change,stop"}).json()
    statuses = {t["type"]: t["status"] for t in body["types"]}
    assert statuses == {"change": "none_within", "stop": "no_data"}
    assert body["facilities"] == []
    # change was checked (a dataset exists); stops were not (no dataset loaded)
    assert any("change" in sentence.lower() for sentence in body["checked"])
    assert any("transport stops" in sentence for sentence in body["not_checked"])


def test_corridor_defaults_and_never_claims_a_route(client: TestClient):
    body = client.get(CORRIDOR, params={"from": "Preston 3072"}).json()
    assert body["path"]["within_m"] == 500  # config default
    statuses = {t["type"]: t["status"] for t in body["types"]}
    assert set(statuses) == {"toilet", "parking", "stop"}  # default types
    assert statuses["stop"] == "no_data"  # GTFS pending - never "none found"
    assert len(body["not_checked"]) == 3  # step-free + stops + opening hours
    joined = " ".join(body["checked"] + body["not_checked"]).lower()
    assert "route" not in joined  # AC2.3.4: never described as a route


def test_corridor_unknown_venue_is_404(client: TestClient):
    response = client.get("/api/v1/venues/nope/corridor", params={"from": "3072"})
    assert response.status_code == 404


def test_corridor_rejects_a_band_outside_the_config(client: TestClient):
    response = client.get(CORRIDOR, params={"from": "3072", "within": "300"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_distance_band"
