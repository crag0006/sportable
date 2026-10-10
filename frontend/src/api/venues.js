const API_BASE = "/api/v1";

// Matches facility names with the types used by the backend
const FACILITY_TYPE_BY_KEY = {
  toilet: "accessible_toilet",
  parking: "accessible_parking",
  stop: "accessible_transport_stop",
  change: "accessible_change_facility"
};

// Gets a readable error message from the API response
function parseErrorMessage(body, status) {
  if (body?.error?.message) return body.error.message;

  // Handles validation errors returned by the backend
  if (Array.isArray(body?.detail)) {
    const messages = body.detail.map((item) => item.msg).filter(Boolean);
    if (messages.length > 0) return messages.join("; ");
  }

  return `Request failed (${status})`;
}

// Sends a GET request and returns the API response
async function getJSON(path) {
  let response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" }
    });
  } catch {
    throw new Error("Could not reach the SportAble service.");
  }

  const body = await response.json().catch(() => null);

  // Shows an error if the request was unsuccessful
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, response.status));
  }

  return body;
}

// Sends a POST request with data to the backend
async function postJSON(path, payload) {
  let response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch {
    throw new Error("Could not reach the SportAble service.");
  }

  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(parseErrorMessage(body, response.status));
  }

  return body;
}

// Gets the details of a selected venue
export function getVenue(id) {
  return getJSON(`/venues/${encodeURIComponent(id)}`);
}

// Gets the distance settings and result limit from the backend
export function getConfig() {
  return getJSON("/config").then((data) => ({
    distanceBandsM: data.distance_bands_m,
    defaultDistanceM: data.default_distance_m,
    maxResults: data.max_results
  }));
}

// Gets the list of available sports
export function getSports() {
  return getJSON("/sports").then((body) =>
    (body.sports ?? []).map((sport) =>
      typeof sport === "string" ? sport : sport.name
    )
  );
}

// Gets the list of available suburbs
export function getSuburbs() {
  return getJSON("/suburbs").then((body) =>
    (body.suburbs ?? []).map((item) => item.label)
  );
}

// Gets the corridor and nearby facilities for a selected venue
export function getCorridor(venueId, from) {
  const params = new URLSearchParams({ from });
  return getJSON(
    `/venues/${encodeURIComponent(venueId)}/corridor?${params.toString()}`
  );
}

// Searches for venues using the selected filters
export function searchVenues({
  sport,
  suburb,
  toilet,
  parking,
  stop,
  change,
  limit
}) {
  const params = new URLSearchParams();
  params.set("sport", sport);

  const suburbInput = suburb.trim();
  const postcodeMatch = suburbInput.match(/(\d{4})\s*$/);

  // Uses the postcode if one is entered, otherwise uses the suburb
  if (postcodeMatch) {
    params.set("postcode", postcodeMatch[1]);
  } else {
    params.set("suburb", suburbInput);
  }

  // Adds the selected accessibility facilities to the search
  const facilityTypes = [];
  if (toilet) facilityTypes.push(FACILITY_TYPE_BY_KEY.toilet);
  if (parking) facilityTypes.push(FACILITY_TYPE_BY_KEY.parking);
  if (stop) facilityTypes.push(FACILITY_TYPE_BY_KEY.stop);
  if (change) facilityTypes.push(FACILITY_TYPE_BY_KEY.change);

  if (facilityTypes.length > 0) {
    params.set("facilities", facilityTypes.join(","));
  }

  // Adds the selected distance limit
  if (limit) {
    params.set("distance_m", limit);
  }

  // Returns the venue results from the backend
  return getJSON(`/venues/search?${params.toString()}`).then((data) => ({
    total: data.total,
    matched: data.matched,
    undocumented: data.undocumented,
    undocumentedLabel: null,
    place: data.reference_point?.label || data.place,
    distanceLimitM: data.distance_limit_m
  }));
}

// Sends a question and recent chat history to the assistant
export function askAssistant({ question, context, history }) {
  // Keeps only the last six messages for the backend
  const trimmedHistory = (history || []).slice(-6).map((turn) => ({
    role: turn.role,
    content: turn.content
  }));

  // Sends the question with any available page details
  return postJSON("/assistant", {
    question,
    context: context || null,
    history: trimmedHistory
  }).then((data) => ({
    kind: data.kind,
    answer: data.answer,
    results: data.results || null,
    links: data.links || [],
    sources: data.sources || [],
    trace: data.trace || [],
    suggestedQuestions: data.suggested_questions || [],
    calendarProposal: data.calendar_proposal || null,
    notice: data.notice,
    modelCalled: data.model_called,
    partial: data.partial
  }));
}
