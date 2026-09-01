// This file is the only place in the app that talks to the backend.
// Every web address here starts with /api/v1.

const API_BASE = "/api/v1";

// Our code uses short names like "toilet" and "parking".
// The backend uses longer names like "accessible_toilet" when we ask it
// to filter search results by facility.
const FACILITY_TYPE_BY_KEY = {
  toilet: "accessible_toilet",
  parking: "accessible_parking",
  stop: "accessible_transport_stop",
  change: "accessible_change_facility",
};

// A small helper used by every function below. It fetches data from the
// backend. If something goes wrong, it shows the backend's own error
// message instead of just failing silently.
async function getJSON(path) {
  const response = await fetch(`${API_BASE}${path}`);

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error?.message || `Request failed (${response.status})`;
    throw new Error(message);
  }

  return response.json();
}

// Gets the distance choices (like 250m, 500m, 1km) from the backend,
// so we never have to type them into the code by hand.
export async function getConfig() {
  const data = await getJSON("/config");

  return {
    distanceBandsM: data.distance_bands_m,
    defaultDistanceM: data.default_distance_m,
  };
}

// Gets the list of sport names, for the sport dropdown.
// The real backend sends plain strings (e.g. "Basketball"), not objects.
export async function getSports() {
  const data = await getJSON("/sports");
  return data.sports.map((sport) =>
    typeof sport === "string" ? sport : sport.name
  );
}

// Gets the list of suburb display labels, for the suburb dropdown.
// Each real entry looks like { suburb, postcode, label }, e.g.
// { suburb: "Preston", postcode: "3072", label: "Preston 3072" }.
// We show the label, since some suburb names repeat with different
// postcodes, and the label disambiguates them.
export async function getSuburbs() {
  const data = await getJSON("/suburbs");
  return data.suburbs.map((suburb) => suburb.label);
}

// Sends the search form to the backend, and returns the results in the
// shape the rest of the app expects.
//
// Note: the venue objects the backend sends back already come in the
// shape our components need — amenities keyed by short names like
// "toilet", and distance already in kilometres for the venue and metres
// for each amenity — so unlike sports/suburbs, nothing needs converting
// here. We just pass them straight through.
export async function searchVenues({ sport, suburb, toilet, parking, stop, change, limit }) {
  const params = new URLSearchParams();
  params.set("sport", sport);

  // The suburb box can hold a bare postcode ("3072"), or a suburb picked
  // from the dropdown which looks like "Preston 3072". Either way, if
  // there's a 4-digit number at the end, use that as the postcode — it's
  // more precise and avoids ambiguity when a suburb name has more than
  // one postcode.
  const suburbInput = suburb.trim();
  const postcodeMatch = suburbInput.match(/(\d{4})\s*$/);

  if (postcodeMatch) {
    params.set("postcode", postcodeMatch[1]);
  } else {
    params.set("suburb", suburbInput);
  }

  // Turn the ticked checkboxes into the list of names the backend expects.
  const facilityTypes = [];
  if (toilet) facilityTypes.push(FACILITY_TYPE_BY_KEY.toilet);
  if (parking) facilityTypes.push(FACILITY_TYPE_BY_KEY.parking);
  if (stop) facilityTypes.push(FACILITY_TYPE_BY_KEY.stop);
  if (change) facilityTypes.push(FACILITY_TYPE_BY_KEY.change);

  if (facilityTypes.length > 0) {
    params.set("facilities", facilityTypes.join(","));
  }

  // If no distance was picked, don't send one — the backend will use its
  // own default and tell us which one it used.
  if (limit) {
    params.set("distance_m", limit);
  }

  const data = await getJSON(`/venues/search?${params.toString()}`);

  return {
    total: data.total,
    matched: data.matched,
    undocumented: data.undocumented,
    undocumentedLabel: null, // the backend doesn't send a custom heading right now
    place: data.reference_point?.label || data.place,
    distanceLimitM: data.distance_limit_m,
  };
}