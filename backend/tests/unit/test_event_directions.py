"""Directions to an event (US4.2, AC4.2.4).

The same corridor as the venue page, pointed at the event's matched venue, plus
the one thing an event adds: it may not have a matched venue at all.
"""

from fastapi.testclient import TestClient

MATCHED = "/api/v1/events/fx-1/directions"
UNMATCHED = "/api/v1/events/aaaplay:25086/directions"


def test_unknown_event_is_a_404(client: TestClient):
    response = client.get("/api/v1/events/nope/directions", params={"from": "3072"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "event_not_found"


def test_a_matched_event_gets_the_venue_corridor(client: TestClient):
    """AC4.2.4. The route to the event AND the accessible facilities along it."""
    body = client.get(MATCHED, params={"from": "3072"}).json()
    assert body["route_available"] is True
    assert body["event"]["id"] == "fx-1"
    assert body["event"]["href"] == "/events/fx-1"
    corridor = body["corridor"]
    assert corridor["venue"]["id"] == "10432"
    assert corridor["origin"]["label"] == "the centre of postcode 3072"
    assert corridor["path"]["kind"] == "straight_line"
    assert [f["seq"] for f in corridor["facilities"]] == list(
        range(1, len(corridor["facilities"]) + 1)
    )


def test_the_corridor_is_the_venue_corridor_unchanged(client: TestClient):
    """Reused, not reimplemented: two corridors would be two disclaimers to
    forget to update."""
    params = {"from": "3072", "within": "500"}
    from_event = client.get(MATCHED, params=params).json()["corridor"]
    from_venue = client.get("/api/v1/venues/10432/corridor", params=params).json()
    assert from_event == from_venue


def test_an_unmatched_venue_says_no_route_rather_than_an_empty_one(client: TestClient):
    """An empty facility list would read as "we looked and found nothing on the
    way", which is a claim nobody checked."""
    body = client.get(UNMATCHED, params={"from": "3072"}).json()
    assert body["route_available"] is False
    assert body["reason"] == "venue_not_matched"
    assert "not in our venue list" in body["message"]
    assert "Leisure Networks" in body["message"]
    # Explicitly absent, not an empty corridor with an empty facility list.
    assert "corridor" not in body


def test_an_unmatched_venue_does_not_demand_a_starting_point_first(client: TestClient):
    """Asking for an origin and then saying no is two steps to the same answer."""
    response = client.get(UNMATCHED)
    assert response.status_code == 200
    assert response.json()["route_available"] is False


def test_a_matched_event_still_needs_a_starting_point(client: TestClient):
    """AC2.2.1 - there is no default origin, because the facilities on the way
    depend entirely on where the journey begins."""
    response = client.get(MATCHED)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_the_band_and_the_types_are_honoured(client: TestClient):
    body = client.get(
        MATCHED, params={"from": "3072", "within": "250", "types": "accessible_toilet"}
    ).json()
    corridor = body["corridor"]
    assert corridor["path"]["within_m"] == 250
    assert [t["type"] for t in corridor["types"]] == ["accessible_toilet"]
    assert all(f["type"] == "accessible_toilet" for f in corridor["facilities"])


def test_an_unloaded_facility_type_is_not_reported_as_absent(client: TestClient):
    """No dataset loaded and none within the corridor are different
    sentences. Unknown is never a no, on this page as on every other."""
    corridor = client.get(MATCHED, params={"from": "3072"}).json()["corridor"]
    by_type = {t["type"]: t for t in corridor["types"]}
    assert by_type["accessible_transport_stop"]["status"] == "no_data"
    assert "No published information loaded" in by_type["accessible_transport_stop"]["message"]


def test_no_routing_request_is_made(client: TestClient):
    """DS-05 has a request quota and the events page multiplies how often a
    directions view is opened. The corridor comes from our own data, so this
    endpoint spends no quota and cannot fail because a third party is down."""
    for url in (MATCHED, UNMATCHED):
        routing = client.get(url, params={"from": "3072"}).json()["routing"]
        assert routing["status"] == "not_used"
        assert "openrouteservice" in routing["provider"]
        assert "quota" in routing["note"]


def test_the_straight_line_is_never_called_a_route(client: TestClient):
    body = client.get(MATCHED, params={"from": "3072"}).json()
    assert "straight-line corridor" in body["corridor"]["disclaimer"]
    assert "not a checked route" in body["routing"]["note"]
