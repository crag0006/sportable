const BASE_PATH = "/api/v1";

function buildQueryString(params) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, value);
  });

  return query.toString();
}

export async function getEvents({ sport, suburb, dateFrom, dateTo } = {}) {
  const queryString = buildQueryString({
    sport,
    suburb,
    from: dateFrom,
    to: dateTo,
  });

  const response = await fetch(`${BASE_PATH}/events?${queryString}`);

  if (!response.ok) {
    let message = "Could not reach the SportAble service. Please try again.";

    try {
      const body = await response.json();
      if (body?.error?.message) {
        message = body.error.message;
      }
    } catch {
      // Response wasn't JSON — keep the default message.
    }

    throw new Error(message);
  }

  return response.json();
}