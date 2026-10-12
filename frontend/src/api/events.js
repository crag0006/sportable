
const BASE_PATH = "/api/v1";

// Builds a query string using the provided search filters
function buildQueryString(params) {
  const query = new URLSearchParams();

  // Adds only the parameters that have values
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, value);
  });

  return query.toString();
}

// Gets events based on the selected search filters
// Also supports searches by venue ID or specific event IDs
export async function getEvents({
  sport,
  suburb,
  dateFrom,
  dateTo,
  weekday,
  venueId,
  ids,
} = {}) {
  // Prepares the search parameters for the API
  const queryString = buildQueryString({
    sport,
    suburb,
    from: dateFrom,
    to: dateTo,
    weekday,
    venue_id: venueId,
    ids: Array.isArray(ids) ? ids.join(",") : ids,
  });

  // Sends the request to get matching events
  const response = await fetch(`${BASE_PATH}/events?${queryString}`);

  // Handles errors returned by the API
  if (!response.ok) {
    let message = "Could not reach the SportAble service. Please try again.";

    try {
      const body = await response.json();
      if (body?.error?.message) {
        message = body.error.message;
      }
    } catch {
      // Uses the default message if the response is not valid JSON
    }

    throw new Error(message);
  }

  // Returns the event data from the backend
  return response.json();
}