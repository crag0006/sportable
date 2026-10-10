import { useEffect, useState } from "react";
import TopBar from "../components/TopBar";
import "./Home.css";
import { getSports, getSuburbs } from "../api/venues";
import { getEvents } from "../api/events";
import { FACILITY_INFO } from "../components/SearchVenue";
import ReadAloud from "../components/ReadAloud";
import {
  addSavedEvent,
  isEventSaved,
  removeSavedEvent
} from "../components/savedEvents";

// Key used to save the last event search
const STORAGE_KEY = "sportable-last-event-search";

// Matches API facility types with the names used in the app
const EVENT_FACILITY_TYPE_TO_KEY = {
  accessible_toilet: "toilet",
  accessible_parking: "parking",
  accessible_transport_stop: "stop",
  accessible_change_facility: "change"
};

// Gets the previous event search from session storage
function getSavedSearch() {
  try {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch {}
  return null;
}

// Finds sports that match the entered text
function findSportMatches(list, typedText) {
  if (typedText.length === 0) return list;
  return list.filter((item) =>
    item.toLowerCase().includes(typedText.toLowerCase())
  );
}

// Finds matching suburbs when at least three characters are entered
function findSuburbMatches(list, typedText) {
  if (typedText.length < 3) return [];
  return list.filter((item) =>
    item.toLowerCase().includes(typedText.toLowerCase())
  );
}

// Creates a Google Maps directions link to the venue
function buildMapsUrl(lat, lon) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`;
}

// Formats the event date and time for display
function formatEventDateTime(event) {
  if (event.date_local) {
    const date = new Date(`${event.date_local}T${event.time_local || "00:00"}`);
    const dateText = date.toLocaleDateString("en-AU", {
      weekday: "short",
      day: "numeric",
      month: "short"
    });

    if (!event.time_local) return dateText;

    const timeText = date
      .toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" })
      .toLowerCase();

    return `${dateText} · ${timeText}`;
  }

  // Shows the repeat schedule for recurring activities
  if (event.recurrence?.summary) {
    return event.status_label
      ? `${event.status_label} · ${event.recurrence.summary}`
      : event.recurrence.summary;
  }

  // Shows the weekday when an exact time is not published
  if (event.weekday) {
    const label = `Every ${event.weekday}`;
    return event.activity_when ? `${label} · ${event.activity_when}` : label;
  }

  if (event.status_label) return event.status_label;

  return "Date to be confirmed";
}

// Checks the availability status of an event facility
export function getEventFacilityState(facility) {
  if (!facility) return "unknown";

  if (facility.display === "at_venue") return "at-venue";
  if (facility.display === "beyond_limit") return "beyond";
  if (facility.display === "within_limit") return "within";

  if (facility.status === "not_available" || facility.status === "absent") {
    return "absent";
  }

  return "unknown";
}

// Returns the message shown for each facility status
function getEventFacilityText(facility, state) {
  if (state === "at-venue") return "At the venue";

  if (state === "within") {
    return facility.distance_m !== undefined && facility.distance_m !== null
      ? facility.distance_m + " m away"
      : "Distance unknown";
  }

  if (state === "beyond") {
    const distanceText =
      facility.distance_m !== undefined && facility.distance_m !== null
        ? facility.distance_m + " m away"
        : "Distance unknown";
    return facility.distance_limit_m
      ? `${distanceText} (beyond ${facility.distance_limit_m} m)`
      : distanceText;
  }

  if (state === "absent") return "Not available";

  return "No published information — check with the venue";
}

// Returns a symbol for the facility status
function getEventFacilityStatusSymbol(state) {
  if (state === "at-venue" || state === "within") return "✓";
  if (state === "beyond") return "!";
  if (state === "absent") return "✕";
  return "?";
}

function EventCard({ event }) {
  // Gets the event's venue, links and accessibility details
  const venue = event.venue || {};
  const links = event.links || {};
  const access = event.access || {};
  const facilities = access.facilities || [];

  const venueHref = venue.href;
  const directionsHref = links.directions;

  // Checks whether the venue's map coordinates are available
  const hasVenueCoordinates =
    venue.latitude !== undefined &&
    venue.latitude !== null &&
    venue.longitude !== undefined &&
    venue.longitude !== null;

  // Uses team names or the event title
  const eventTitle =
    event.home_team && event.away_team
      ? `${event.home_team} v ${event.away_team}`
      : event.title || event.sport;

  // Checks whether this event is already saved
  const [isSaved, setIsSaved] = useState(() => isEventSaved(event.id));

  // Saves or removes the selected event
  function handleToggleSave() {
    if (isSaved) {
      removeSavedEvent(event.id);
      setIsSaved(false);
      return;
    }

    // Saves the event details for the Saved Events page
    addSavedEvent({
      id: event.id,
      title: eventTitle,
      sport: event.sport,
      dateTimeLabel: formatEventDateTime(event),
      suburb: venue.suburb || venue.address || "",
      venueName: venue.name || "Venue to be confirmed",

      // Keeps the original date and time for Google Calendar
      dateLocal: event.date_local || null,
      timeLocal: event.time_local || null,
      venueAddress: venue.address || "",
      venueHref: venue.href || null,
      facilities: facilities,

      // Keeps details needed for weekly recurring activities
      weekday: event.weekday || null,
      activityWhen: event.activity_when || null,
      description: event.description || "",
      externalLink: event.links?.external || null,
      registrationLink: event.links?.registration || null,

      // Keeps the calendar details provided by the API
      calendarBlock: event.calendar || null
    });

    setIsSaved(true);
  }

  return (
    <article className="event-card">
      {/* Event name, sport and date */}
      <div className="event-top">
        <div>
          <span className="chip">{event.sport}</span>

          <h3 className="event-teams">{eventTitle}</h3>

          <p className="event-meta">
            {[event.competition, event.grade, event.round]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>

        <div className="event-top-right">
          <span className="event-datetime">{formatEventDateTime(event)}</span>

          {/* Shows the map link when venue coordinates are available */}
          {hasVenueCoordinates && (
            <a
              className="event-map-button"
              href={buildMapsUrl(venue.latitude, venue.longitude)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open ${venue.name || "venue"} in Google Maps`}
              title="Open in Google Maps"
            >
              <span aria-hidden="true">🧭</span>
              Map
            </a>
          )}
        </div>
      </div>

      {/* Venue name and address */}
      <div className="event-venue">
        <div>
          <p className="event-venue-name">
            {venue.name || "Venue to be confirmed"}
          </p>
          {venue.address && (
            <p className="event-venue-address">{venue.address}</p>
          )}
        </div>
      </div>

      {/* Displays the accessibility facilities for the event venue */}
      {facilities.length > 0 && (
        <div className="amenity-grid">
          {facilities.map((facility) => {
            const key = EVENT_FACILITY_TYPE_TO_KEY[facility.type];
            if (!key || !FACILITY_INFO[key]) return null;

            const state = getEventFacilityState(facility);

            return (
              <div
                key={facility.type}
                className={"amenity-box amenity-" + state}
              >
                <span className="facility-icon" aria-hidden="true">
                  {FACILITY_INFO[key].icon}
                </span>

                <div className="amenity-content">
                  <strong>{FACILITY_INFO[key].name}</strong>
                  <p>{getEventFacilityText(facility, state)}</p>
                </div>

                <span
                  className={"status-symbol status-" + state}
                  aria-label={state}
                >
                  {getEventFacilityStatusSymbol(state)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Buttons to save the event or view venue details */}
      <div className="event-actions">
        <button
          type="button"
          className="event-action-link event-action-link--secondary save-event-button"
          onClick={handleToggleSave}
          aria-pressed={isSaved}
          aria-label={isSaved ? `Unsave ${eventTitle}` : `Save ${eventTitle}`}
          style={{
            appearance: "none",
            WebkitAppearance: "none",
            MozAppearance: "none",
            font: "inherit",
            lineHeight: "inherit",
            boxSizing: "border-box",
            cursor: "pointer",
            alignSelf: "center"
          }}
        >
          <span aria-hidden="true">{isSaved ? "★" : "☆"}</span>{" "}
          {isSaved ? "Saved" : "Save"}
        </button>

        {venueHref && (
          <a
            className="event-action-link event-action-link--secondary"
            href={venueHref}
          >
            View venue
          </a>
        )}

        {directionsHref && (
          <a
            className="event-action-link event-action-link--primary"
            href={directionsHref}
          >
            Get directions
          </a>
        )}

        {/* Message shown when venue details are unavailable */}
        {!venueHref && !directionsHref && (
          <p
            className="venue-unavailable-note"
            style={{ margin: 0, alignSelf: "center" }}
          >
            Venue details not available for this event.
          </p>
        )}
      </div>
    </article>
  );
}

function Events() {
  // Stores the sports and suburbs received from the API
  const [sports, setSports] = useState([]);
  const [suburbs, setSuburbs] = useState([]);

  // Restores the previous search filters if available
  const [sport, setSport] = useState(() => getSavedSearch()?.sport ?? "");
  const [suburb, setSuburb] = useState(() => getSavedSearch()?.suburb ?? "");
  const [dateFrom, setDateFrom] = useState(
    () => getSavedSearch()?.dateFrom ?? ""
  );
  const [dateTo, setDateTo] = useState(() => getSavedSearch()?.dateTo ?? "");

  // Controls the sport and suburb suggestion lists
  const [showSports, setShowSports] = useState(false);
  const [showSuburbs, setShowSuburbs] = useState(false);

  // Stores the search results and controls the search form
  const [results, setResults] = useState(
    () => getSavedSearch()?.results ?? null
  );
  const [showForm, setShowForm] = useState(() => !getSavedSearch()?.results);

  // Stores form errors and loading status
  const [formError, setFormError] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  // Number of event cards currently displayed
  const [visibleCount, setVisibleCount] = useState(
    () => getSavedSearch()?.visibleCount ?? 5
  );

  // Loads the available sports and suburbs when the page opens
  useEffect(() => {
    getSports()
      .then((data) => setSports(data))
      .catch(() =>
        setSports(["Badminton", "Basketball", "Netball", "Swimming", "Tennis"])
      );

    getSuburbs()
      .then((data) => setSuburbs(data))
      .catch(() =>
        setSuburbs([
          "Melbourne",
          "Carlton",
          "Fitzroy",
          "North Melbourne",
          "Preston",
          "Kensington"
        ])
      );
  }, []);

  // Checks the search details and fetches matching events
  async function handleSearch(event) {
    event.preventDefault();

    if (sport === "" && suburb === "") {
      setFormError("Choose a sport and a suburb or postcode.");
      return;
    }
    if (sport === "") {
      setFormError("Choose a sport.");
      return;
    }
    if (suburb === "") {
      setFormError("Choose a suburb or postcode.");
      return;
    }
    if (dateFrom && dateTo && dateFrom > dateTo) {
      setFormError("The 'from' date must be before the 'to' date.");
      return;
    }

    setFormError("");
    setShowSports(false);
    setShowSuburbs(false);
    setIsSearching(true);
    setSearchError("");

    try {
      const data = await getEvents({ sport, suburb, dateFrom, dateTo });

      // Stores the results along with the selected filters
      const newResults = {
        events: data.events || [],
        window: data.window,
        referenceLabel: data.reference_point?.label,
        emptyMessage: data.empty_message,
        searchedSport: sport,
        searchedPlace: suburb,
        searchedDateFrom: dateFrom,
        searchedDateTo: dateTo
      };

      setResults(newResults);
      setVisibleCount(5);
      setShowForm(false);

      // Remembers that the last results page was Events
      try {
        sessionStorage.setItem("sportable-last-results-page", "/events");
      } catch {
        // Continues if session storage is unavailable
      }

      // Saves the search so it can be restored later
      try {
        sessionStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            sport,
            suburb,
            dateFrom,
            dateTo,
            results: newResults,
            visibleCount: 5
          })
        );
      } catch {}
    } catch (error) {
      // Displays an error if the event search fails
      setSearchError(
        error.message ||
          "Something went wrong loading events. Please try again."
      );
    } finally {
      setIsSearching(false);
    }
  }

  // Clears all search filters and previous results
  function handleClear() {
    setSport("");
    setSuburb("");
    setDateFrom("");
    setDateTo("");
    setResults(null);
    setShowForm(true);
    setFormError("");
    setSearchError("");
    setShowSports(false);
    setShowSuburbs(false);

    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {}
  }

  // Gets matching suggestions for the entered sport and suburb
  const sportMatches = findSportMatches(sports, sport);
  const suburbMatches = findSuburbMatches(suburbs, suburb);

  // Creates the selected date range text
  function buildDateRangeText() {
    if (!results) return "";
    if (results.searchedDateFrom && results.searchedDateTo) {
      return `${results.searchedDateFrom} to ${results.searchedDateTo}`;
    }
    return "";
  }

  // Creates a summary of the current search
  function buildSummaryText() {
    if (!results) return "";
    let text = results.searchedSport + " near " + results.searchedPlace;
    const dateRangeText = buildDateRangeText();
    if (dateRangeText) {
      text = text + " · " + dateRangeText;
    }
    return text;
  }

  // Creates a message when no matching events are found
  function buildEmptyMessage() {
    if (!results) return "";

    let message = `No ${results.searchedSport} events found near ${results.searchedPlace}`;

    const dateRangeText = buildDateRangeText();
    if (dateRangeText) {
      message += ` between ${results.searchedDateFrom} and ${results.searchedDateTo}`;
    }

    message +=
      ". Try a wider date range, remove a filter, or try a nearby suburb.";

    return message;
  }

  // Prepares a short summary of the search results for Read Aloud
  function buildReadAloudSummary() {
    if (!results) return [];

    const sentences = [`${buildSummaryText()}.`];

    if (results.events.length === 0) {
      sentences.push(buildEmptyMessage());
      return sentences;
    }

    sentences.push(
      `${results.events.length} event${results.events.length === 1 ? "" : "s"} found.`
    );

    const firstEvent = results.events[0];
    const firstVenueName = firstEvent.venue?.name || "a venue to be confirmed";
    sentences.push(`Next up: ${firstEvent.sport} at ${firstVenueName}.`);

    return sentences;
  }

  return (
    <div className="search-page">
      {/* Top navigation bar */}
      <TopBar
        links={[
          { to: "/", label: "Home" },
          { to: "/venues", label: "Venue search" },
          { to: "/saved-events", label: "Saved events" }
        ]}
      />

      <main className="search-content">
        {/* Events page banner */}
        <div className="search-banner-wrap">
          <div className="page-kicker">Explore sports events</div>

          <div className="search-banner">
            <div className="search-banner-overlay">
              <p className="search-banner-text">
                No more maybes — every step, mapped out.
              </p>
            </div>
          </div>
        </div>

        {/* Shows the search details after results are loaded */}
        {results !== null && !showForm && (
          <div className="search-summary-bar">
            <div>
              <span className="search-summary-label">Your search</span>
              <strong className="search-summary-text">
                {buildSummaryText()}
              </strong>
            </div>

            <div className="search-summary-actions">
              <button
                type="button"
                className="edit-search-button"
                onClick={() => setShowForm(true)}
              >
                Update filters
              </button>

              <button
                type="button"
                className="clear-button"
                onClick={handleClear}
              >
                Clear
              </button>
            </div>
          </div>
        )}

        {/* Event search form */}
        {showForm && (
          <section className="search-card">
            <h1 className="search-title">Search for an event</h1>

            <form onSubmit={handleSearch}>
              <div className="search-row">
                {/* Sport search field */}
                <div className="field">
                  <label htmlFor="event-sport">
                    Sport <span className="required">*</span>
                  </label>

                  <div className="field-inner">
                    <input
                      id="event-sport"
                      type="text"
                      className="input"
                      placeholder="eg: Basketball"
                      autoComplete="off"
                      value={sport}
                      onFocus={() => setShowSports(true)}
                      onBlur={() => {
                        window.setTimeout(() => setShowSports(false), 0);
                      }}
                      onChange={(event) => {
                        setSport(event.target.value);
                        setShowSports(true);
                      }}
                    />

                    {/* Shows matching sport suggestions */}
                    {showSports && sportMatches.length > 0 && (
                      <ul className="suggestions">
                        {sportMatches.map((item) => (
                          <li key={item}>
                            <button
                              type="button"
                              tabIndex={-1}
                              onMouseDown={(event) => {
                                event.preventDefault();
                                setSport(item);
                                setShowSports(false);
                              }}
                            >
                              {item}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {showSports &&
                    sport.length > 0 &&
                    sportMatches.length === 0 && (
                      <p className="no-match">No sport found with that name.</p>
                    )}

                  <p className="field-hint">
                    Select sports from the drop down or type min 3 characters to
                    search.
                  </p>
                </div>

                {/* Suburb or postcode search field */}
                <div className="field">
                  <label htmlFor="event-suburb">
                    Suburb or postcode <span className="required">*</span>
                  </label>

                  <div className="field-inner">
                    <input
                      id="event-suburb"
                      type="text"
                      className="input"
                      placeholder="eg: Melbourne CBD or 3000"
                      autoComplete="off"
                      value={suburb}
                      onChange={(event) => {
                        setSuburb(event.target.value);
                        setShowSuburbs(true);
                      }}
                    />

                    {/* Shows matching suburb suggestions */}
                    {showSuburbs && suburbMatches.length > 0 && (
                      <ul className="suggestions">
                        {suburbMatches.map((item) => (
                          <li key={item}>
                            <button
                              type="button"
                              tabIndex={-1}
                              onClick={() => {
                                setSuburb(item);
                                setShowSuburbs(false);
                              }}
                            >
                              {item}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {showSuburbs &&
                    suburb.length >= 3 &&
                    suburbMatches.length === 0 &&
                    !/^\d+$/.test(suburb) && (
                      <p className="no-match">
                        Try a Greater Melbourne suburb or postcode.
                      </p>
                    )}

                  <p className="field-hint">
                    Enter minimum 3 letters or numbers to search.
                  </p>
                </div>
              </div>

              {/* Optional date filters */}
              <div className="date-section">
                <p className="date-section-title">Choose your dates</p>
                <div className="search-row">
                  <div className="field">
                    <label htmlFor="event-date-from">From</label>
                    <input
                      id="event-date-from"
                      type="date"
                      className={dateFrom ? "input" : "input input-date-empty"}
                      value={dateFrom}
                      onChange={(event) => setDateFrom(event.target.value)}
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="event-date-to">To</label>
                    <input
                      id="event-date-to"
                      type="date"
                      className={dateTo ? "input" : "input input-date-empty"}
                      value={dateTo}
                      min={dateFrom || undefined}
                      onChange={(event) => setDateTo(event.target.value)}
                    />
                  </div>
                </div>
              </div>

              {/* Displays form validation errors */}
              {formError !== "" && (
                <p className="form-error" role="alert">
                  {formError}
                </p>
              )}

              {/* Displays errors from the event search API */}
              {searchError !== "" && (
                <p className="form-error" role="alert">
                  {searchError}
                </p>
              )}

              {/* Buttons to clear the form or search for events */}
              <div className="buttons">
                <button
                  type="button"
                  className="clear-button"
                  onClick={handleClear}
                >
                  Clear
                </button>

                <button
                  type="submit"
                  className="search-button"
                  disabled={isSearching}
                >
                  {isSearching ? "Searching…" : "Search events"}
                </button>
              </div>
            </form>
          </section>
        )}

        {/* Displays search results or the initial message */}
        <div aria-live="polite">
          {results === null ? (
            <section className="results-empty">
              <h2>Nothing searched yet</h2>
              <p>
                Choose a sport and a location, and pick a date range if you
                like, then select Search events.
              </p>
            </section>
          ) : (
            <div className="results">
              {/* Reads a short summary of the search results */}
              <ReadAloud summary={buildReadAloudSummary()} />

              {/* Number of events found */}
              <div className="results-heading">
                <div>
                  <h2>{results.events.length} events found</h2>
                  <p>
                    {results.searchedSport} events near {results.searchedPlace}
                    {buildDateRangeText() ? ` · ${buildDateRangeText()}` : ""}
                  </p>
                </div>
              </div>

              {/* Message displayed when no events match the search */}
              {results.events.length === 0 && (
                <div className="empty-card">
                  <h3>No matching events</h3>
                  <p>{buildEmptyMessage()}</p>
                </div>
              )}

              {/* Displays matching event cards */}
              {results.events.slice(0, visibleCount).map((event) => (
                <EventCard key={event.id} event={event} />
              ))}

              {/* Loads five more events when clicked */}
              {visibleCount < results.events.length && (
                <button
                  type="button"
                  className="view-more-button"
                  onClick={() => setVisibleCount(visibleCount + 5)}
                >
                  View more events ({results.events.length - visibleCount} more)
                </button>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default Events;
