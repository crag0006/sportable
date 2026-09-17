import { useEffect, useState } from "react";
import TopBar from "../components/TopBar";
import "./Home.css";
import { getSports, getSuburbs } from "../api/venues";
import { getEvents } from "../api/events";

const STORAGE_KEY = "sportable-last-event-search";

function getSavedSearch() {
  try {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch {
   
  }
  return null;
}

function findSportMatches(list, typedText) {
  if (typedText.length === 0) return list;
  return list.filter((item) =>
    item.toLowerCase().includes(typedText.toLowerCase())
  );
}

function findSuburbMatches(list, typedText) {
  if (typedText.length < 3) return [];
  return list.filter((item) =>
    item.toLowerCase().includes(typedText.toLowerCase())
  );
}

function formatEventDistance(meters) {
  if (meters === null || meters === undefined) return null;
  if (meters >= 1000) return (meters / 1000).toFixed(1) + "km away";
  return meters + "m away";
}

function formatEventDateTime(dateLocal, timeLocal) {
  if (!dateLocal) return "Date to be confirmed";
  const date = new Date(`${dateLocal}T${timeLocal || "00:00"}`);
  const dateText = date.toLocaleDateString("en-AU", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  if (!timeLocal) return dateText;
  const timeText = date
    .toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" })
    .toLowerCase();
  return `${dateText} · ${timeText}`;
}

function EventCard({ event }) {
  const distanceLabel = formatEventDistance(event.distance_m);
  const venue = event.venue || {};
  const links = event.links || {};
  const access = event.access || {};

  const venueHref = venue.href;
  const directionsHref = links.directions;
  const accessSummary = access.summary;

  return (
    <article className="event-card">
      <div className="event-top">
        <div>
          <span className="chip">{event.sport}</span>
          <h3 className="event-teams">
            {event.home_team && event.away_team
              ? `${event.home_team} v ${event.away_team}`
              : event.title}
          </h3>
          <p className="event-meta">
            {[event.competition, event.grade, event.round]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>

        <span className="event-datetime">
          {formatEventDateTime(event.date_local, event.time_local)}
        </span>
      </div>

      <div className="event-venue">
        <div>
          <p className="event-venue-name">
            {venue.name || "Venue to be confirmed"}
          </p>
          {venue.address && (
            <p className="event-venue-address">{venue.address}</p>
          )}
        </div>

        {distanceLabel && (
          <span className="distance-pill">{distanceLabel}</span>
        )}
      </div>

      {accessSummary && (
        <p className="event-access-summary">{accessSummary}</p>
      )}

      <div className="event-actions">
        {venueHref && (
          
           <a className="event-action-link event-action-link--secondary"
            href={venueHref}>
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
      </div>
    </article>
  );
}

function Events() {
  const [sports, setSports] = useState([]);
  const [suburbs, setSuburbs] = useState([]);

  const [sport, setSport] = useState(() => getSavedSearch()?.sport ?? "");
  const [suburb, setSuburb] = useState(() => getSavedSearch()?.suburb ?? "");
  const [dateFrom, setDateFrom] = useState(() => getSavedSearch()?.dateFrom ?? "");
  const [dateTo, setDateTo] = useState(() => getSavedSearch()?.dateTo ?? "");

  const [showSports, setShowSports] = useState(false);
  const [showSuburbs, setShowSuburbs] = useState(false);

  const [results, setResults] = useState(() => getSavedSearch()?.results ?? null);
  const [showForm, setShowForm] = useState(() => !getSavedSearch()?.results);

  const [formError, setFormError] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  const [visibleCount, setVisibleCount] = useState(
    () => getSavedSearch()?.visibleCount ?? 5
  );

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
          "Kensington",
        ])
      );
  }, []);

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

      const newResults = {
        events: data.events || [],
        window: data.window,
        referenceLabel: data.reference_point?.label,
        emptyMessage: data.empty_message,
        searchedSport: sport,
        searchedPlace: suburb,
      };

      setResults(newResults);
      setVisibleCount(5);
      setShowForm(false);

      try {
        sessionStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            sport,
            suburb,
            dateFrom,
            dateTo,
            results: newResults,
            visibleCount: 5,
          })
        );
      } catch {
       
      }
    } catch (error) {
      setSearchError(
        error.message || "Something went wrong loading events. Please try again."
      );
    } finally {
      setIsSearching(false);
    }
  }

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
    } catch {      
    }
  }

  const sportMatches = findSportMatches(sports, sport);
  const suburbMatches = findSuburbMatches(suburbs, suburb);

  function buildSummaryText() {
    if (!results) return "";
    let text = results.searchedSport + " near " + results.searchedPlace;
    if (results.window?.from && results.window?.to) {
      text = text + " · " + results.window.from + " to " + results.window.to;
    }
    return text;
  }

  return (
    <div className="search-page">
      <TopBar
        links={[
          { to: "/", label: "Home" },
          { to: "/venues", label: "Venue search" },
        ]}
      />

      <main className="search-content">
        <div className="search-banner">
          <div className="search-banner-overlay">
            <p className="search-banner-text">
             No more maybes — every step, mapped out.
            </p>
          </div>
        </div>

        {results !== null && !showForm && (
          <div className="search-summary-bar">
            <div>
              <span className="search-summary-label">Your search</span>
              <strong className="search-summary-text">{buildSummaryText()}</strong>
            </div>

            <div className="search-summary-actions">
              <button type="button" className="edit-search-button" onClick={() => setShowForm(true)}>
                Edit search
              </button>
              <button type="button" className="clear-button" onClick={handleClear}>
                Clear
              </button>
            </div>
          </div>
        )}

        {showForm && (
          <section className="search-card">
            <h1 className="search-title">Find an event</h1>

            <form onSubmit={handleSearch}>
              <div className="search-row">
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

                  {showSports && sport.length > 0 && sportMatches.length === 0 && (
                    <p className="no-match">No sport found with that name.</p>
                  )}

                  <p className="field-hint">
                    Select sports from the drop down or type min 3 characters to search.
                  </p>
                </div>

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
                      <p className="no-match">Try a Greater Melbourne suburb or postcode.</p>
                    )}

                  <p className="field-hint">Enter minimum 3 letters or numbers to search.</p>
                </div>
              </div>

              <div className="search-row">
                <div className="field">
                  <label htmlFor="event-date-from">Date from</label>
                  <input
                    id="event-date-from"
                    type="date"
                    className={dateFrom ? "input" : "input input-date-empty"}
                    value={dateFrom}
                    onChange={(event) => setDateFrom(event.target.value)}
                  />
                  <p className="field-hint">Leave blank to include all upcoming dates.</p>
                </div>

                <div className="field">
                  <label htmlFor="event-date-to">Date to</label>
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

              {formError !== "" && (
                <p className="form-error" role="alert">{formError}</p>
              )}

              {searchError !== "" && (
                <p className="form-error" role="alert">{searchError}</p>
              )}

              <div className="buttons">
                <button type="button" className="clear-button" onClick={handleClear}>
                  Clear
                </button>
                <button type="submit" className="search-button" disabled={isSearching}>
                  {isSearching ? "Searching…" : "Search events"}
                </button>
              </div>
            </form>
          </section>
        )}

        <div aria-live="polite">
          {results === null ? (
            <section className="results-empty">
              <h2>Nothing searched yet</h2>
              <p>
                Choose a sport and a location, and pick a date range if you like, then select Search events.
              </p>
            </section>
          ) : (
            <div className="results">
              <div className="results-heading">
                <div>
                  <h2>{results.events.length} events found</h2>
                  <p>
                    {results.searchedSport} events near {results.searchedPlace}
                    {results.window?.from && results.window?.to
                      ? ` · ${results.window.from} to ${results.window.to}`
                      : ""}
                  </p>
                </div>
              </div>

              {results.events.length === 0 && (
                <div className="empty-card">
                  <h3>No matching events</h3>
                  <p>{results.emptyMessage || "Try a wider date range or a different suburb."}</p>
                </div>
              )}

              {results.events.slice(0, visibleCount).map((event) => (
                <EventCard key={event.id} event={event} />
              ))}

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