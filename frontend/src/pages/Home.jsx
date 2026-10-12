import { useState, useEffect } from "react";
import TopBar from "../components/TopBar";
import VenueCard, { FACILITY_INFO } from "../components/SearchVenue";
import ReadAloud from "../components/ReadAloud";
import "./Home.css";
import { getSports, getSuburbs, getConfig, searchVenues } from "../api/venues";
import Chatbot from "../components/Chatbot";
import "../components/Chatbot.css";

// Gets the previous venue search from session storage
function getSavedSearch() {
  try {
    const saved = sessionStorage.getItem("sportable-last-search");
    if (saved) {
      return JSON.parse(saved);
    }
  } catch {}
  return null;
}

// Matches API facility types with the search filter names
const FACILITY_TYPE_TO_KEY = {
  accessible_toilet: "toilet",
  accessible_parking: "parking",
  accessible_transport_stop: "stop",
  accessible_change_facility: "change"
};

// Displays distances as metres or kilometres
function formatDistanceLabel(meters) {
  if (meters >= 1000) {
    return meters / 1000 + "km";
  }
  return meters + "m";
}

function Home() {
  // Stores sports and suburbs loaded from the API
  const [sports, setSports] = useState([]);
  const [suburbs, setSuburbs] = useState([]);

  // Available distance choices for accessibility facilities
  const [distanceBands, setDistanceBands] = useState([250, 500, 1000]);

  // Restores the previous search filters when available
  const [sport, setSport] = useState(() => getSavedSearch()?.sport ?? "");
  const [suburb, setSuburb] = useState(() => getSavedSearch()?.suburb ?? "");
  const [toilet, setToilet] = useState(() => getSavedSearch()?.toilet ?? false);
  const [parking, setParking] = useState(
    () => getSavedSearch()?.parking ?? false
  );
  const [stop, setStop] = useState(() => getSavedSearch()?.stop ?? false);
  const [change, setChange] = useState(() => getSavedSearch()?.change ?? false);
  const [limit, setLimit] = useState(() => getSavedSearch()?.limit ?? "");

  // Controls when the suggestion lists are shown
  const [showSports, setShowSports] = useState(false);
  const [showSuburbs, setShowSuburbs] = useState(false);

  // Tracks the option selected using arrow keys
  const [sportHighlight, setSportHighlight] = useState(-1);
  const [suburbHighlight, setSuburbHighlight] = useState(-1);

  // Stores the venue search results
  const [results, setResults] = useState(
    () => getSavedSearch()?.results ?? null
  );
  const [showForm, setShowForm] = useState(() => !getSavedSearch()?.results);
  const [formError, setFormError] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [showMissing, setShowMissing] = useState(false);

  // Number of venue cards currently displayed
  const [visibleCount, setVisibleCount] = useState(
    () => getSavedSearch()?.visibleCount ?? 5
  );

  // Loads sports, suburbs and distance choices from the API
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

    getConfig()
      .then((data) => setDistanceBands(data.distanceBandsM))
      .catch(() => setDistanceBands([250, 500, 1000]));
  }, []);

  // Closes suggestion lists when clicking outside the search fields
  useEffect(() => {
    function handleDocumentMouseDown(event) {
      if (!event.target.closest?.(".field-inner")) {
        setShowSports(false);
        setShowSuburbs(false);
        setSportHighlight(-1);
        setSuburbHighlight(-1);
      }
    }

    document.addEventListener("mousedown", handleDocumentMouseDown);
    return () =>
      document.removeEventListener("mousedown", handleDocumentMouseDown);
  }, []);

  // Finds suburb suggestions after three characters are entered
  function findMatches(list, typedText) {
    if (typedText.length < 3) {
      return [];
    }

    return list.filter((item) =>
      item.toLowerCase().includes(typedText.toLowerCase())
    );
  }

  // Finds matching sports or shows all sports when the field is empty
  function findSportMatches(list, typedText) {
    if (typedText.length === 0) {
      return list;
    }

    return list.filter((item) =>
      item.toLowerCase().includes(typedText.toLowerCase())
    );
  }

  const sportMatches = findSportMatches(sports, sport);
  const suburbMatches = findMatches(suburbs, suburb);

  // Lets users navigate and select sports using the keyboard
  function handleSportKeyDown(event) {
    if (!showSports || sportMatches.length === 0) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSportHighlight((current) => {
        if (current < sportMatches.length - 1) {
          return current + 1;
        }
        return 0;
      });
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSportHighlight((current) => {
        if (current > 0) {
          return current - 1;
        }
        return sportMatches.length - 1;
      });
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      if (sportHighlight >= 0) {
        setSport(sportMatches[sportHighlight]);
        setShowSports(false);
        setSportHighlight(-1);
      }
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      setShowSports(false);
      setSportHighlight(-1);
    }
  }

  // Lets users navigate and select suburbs using the keyboard
  function handleSuburbKeyDown(event) {
    if (!showSuburbs || suburbMatches.length === 0) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSuburbHighlight((current) => {
        if (current < suburbMatches.length - 1) {
          return current + 1;
        }
        return 0;
      });
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSuburbHighlight((current) => {
        if (current > 0) {
          return current - 1;
        }
        return suburbMatches.length - 1;
      });
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      if (suburbHighlight >= 0) {
        setSuburb(suburbMatches[suburbHighlight]);
        setShowSuburbs(false);
        setSuburbHighlight(-1);
      }
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      setShowSuburbs(false);
      setSuburbHighlight(-1);
    }
  }

  // Runs a venue search using either form values or URL filters
  async function runSearch({
    sport,
    suburb,
    toilet,
    parking,
    stop,
    change,
    limit
  }) {
    const selectedAmenities = [];

    if (toilet) {
      selectedAmenities.push("toilet");
    }
    if (parking) {
      selectedAmenities.push("parking");
    }
    if (stop) {
      selectedAmenities.push("stop");
    }
    if (change) {
      selectedAmenities.push("change");
    }

    setIsSearching(true);
    setSearchError("");

    try {
      const data = await searchVenues({
        sport,
        suburb,
        toilet,
        parking,
        stop,
        change,
        limit
      });

      const newResults = {
        total: data.total,
        matched: data.matched,
        undocumented: data.undocumented,
        undocumentedLabel: data.undocumentedLabel,
        place: data.place,
        searchedSport: sport,
        searchedPlace: suburb,
        searchedLimit: limit,
        selectedAmenities: selectedAmenities
      };

      setResults(newResults);
      setVisibleCount(5);
      setShowForm(false);

      // Remembers that the last results page was venue search
      try {
        sessionStorage.setItem("sportable-last-results-page", "/venues");
      } catch {}

      // Saves the search so it can be restored later
      try {
        sessionStorage.setItem(
          "sportable-last-search",
          JSON.stringify({
            sport,
            suburb,
            toilet,
            parking,
            stop,
            change,
            limit,
            results: newResults,
            visibleCount: 5
          })
        );
      } catch {}
    } catch (error) {
      setSearchError(
        error.message ||
          "Something went wrong loading venues. Please try again."
      );
    } finally {
      setIsSearching(false);
    }
  }

  // Checks the required fields before running a search
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

    setFormError("");
    setShowSports(false);
    setShowSuburbs(false);
    setSportHighlight(-1);
    setSuburbHighlight(-1);

    await runSearch({ sport, suburb, toilet, parking, stop, change, limit });
  }

  // Reads filters from a shared link and runs the search automatically
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);

    const hasUrlParams = params.has("sport") || params.has("suburb");
    if (!hasUrlParams) return;

    const urlSport = params.get("sport") || "";
    const urlSuburb = params.get("suburb") || "";
    const urlLimit = params.get("distance_m") || "";

    const facilityTypes = (params.get("facilities") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

    const urlToilet = facilityTypes.includes("accessible_toilet");
    const urlParking = facilityTypes.includes("accessible_parking");
    const urlStop = facilityTypes.includes("accessible_transport_stop");
    const urlChange = facilityTypes.includes("accessible_change_facility");

    setSport(urlSport);
    setSuburb(urlSuburb);
    setToilet(urlToilet);
    setParking(urlParking);
    setStop(urlStop);
    setChange(urlChange);
    setLimit(urlLimit);

    // Only runs the search when both required fields are available
    if (urlSport && urlSuburb) {
      runSearch({
        sport: urlSport,
        suburb: urlSuburb,
        toilet: urlToilet,
        parking: urlParking,
        stop: urlStop,
        change: urlChange,
        limit: urlLimit
      });
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Clears the filters and previous search results
  function handleClear() {
    setSport("");
    setSuburb("");
    setToilet(false);
    setParking(false);
    setStop(false);
    setChange(false);
    setLimit("");
    setResults(null);
    setShowForm(true);
    setFormError("");
    setSearchError("");
    setShowSports(false);
    setShowSuburbs(false);
    setSportHighlight(-1);
    setSuburbHighlight(-1);

    try {
      sessionStorage.removeItem("sportable-last-search");
    } catch {}
  }

  // Creates a short description of the selected search filters
  function buildSummaryText() {
    if (!results) {
      return "";
    }

    let text = results.searchedSport + " near " + results.searchedPlace;

    if (results.searchedLimit !== "") {
      text =
        text +
        " · " +
        formatDistanceLabel(Number(results.searchedLimit)) +
        " facility limit";
    }

    if (results.selectedAmenities.length > 0) {
      text = text + " · " + results.selectedAmenities.length + " amenities";
    }

    return text;
  }

  // Prepares a short spoken summary of the venue results
  function buildReadAloudSummary() {
    if (!results) {
      return [];
    }

    const sentences = [`${buildSummaryText()}.`];

    const countText =
      results.matched.length === results.total
        ? `${results.total} venues match your search.`
        : `${results.matched.length} of ${results.total} venues found.`;

    sentences.push(countText);

    if (results.matched.length === 0) {
      sentences.push("Try removing an amenity or choosing a bigger distance.");
      return sentences;
    }

    const firstVenue = results.matched[0];
    sentences.push(`Top result: ${firstVenue.name}.`);

    if (results.undocumented.length > 0) {
      sentences.push(
        `${results.undocumented.length} more venues matched but have no published information for the facilities you selected.`
      );
    }

    return sentences;
  }

  return (
    <div>
      {/* Main navigation */}
      <TopBar
        links={[
          {
            to: "/",
            label: "Home"
          },
          {
            to: "/events",
            label: "Events"
          }
        ]}
      />

      <div className="search-page">
        <main className="search-content">
          {/* Venue search page heading and banner */}
          <div className="search-banner-wrap">
            <h2 className="page-heading">
              Explore sports venues with access information
            </h2>

            <div className="search-banner">
              <div className="search-banner-overlay">
                <p className="search-banner-text">
                  No more maybes — every step, mapped out.
                </p>
              </div>
            </div>
          </div>

          {/* Shows the active filters after a search */}
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

          {/* Search form for sport, location and accessibility needs */}
          {showForm && (
            <section className="search-card">
              <h1 className="search-title">Search for a venue</h1>

              <form onSubmit={handleSearch}>
                <div className="search-row">
                  {/* Sport search field */}
                  <div className="field">
                    <label htmlFor="sport">
                      Sport <span className="required">*</span>
                    </label>

                    <div className="field-inner">
                      <input
                        id="sport"
                        type="text"
                        className="input"
                        placeholder="eg: Basketball"
                        autoComplete="off"
                        value={sport}
                        role="combobox"
                        aria-expanded={showSports && sportMatches.length > 0}
                        aria-controls="sport-suggestions"
                        aria-autocomplete="list"
                        aria-activedescendant={
                          sportHighlight >= 0
                            ? `sport-option-${sportHighlight}`
                            : undefined
                        }
                        onFocus={() => {
                          setShowSports(true);
                          setShowSuburbs(false);
                          setSportHighlight(-1);
                        }}
                        onChange={(event) => {
                          setSport(event.target.value);
                          setShowSports(true);
                          setSportHighlight(-1);
                        }}
                        onKeyDown={handleSportKeyDown}
                      />

                      {/* Shows matching sports in a dropdown */}
                      {showSports && sportMatches.length > 0 && (
                        <ul
                          id="sport-suggestions"
                          className="suggestions"
                          role="listbox"
                          aria-label="Sport suggestions"
                        >
                          {sportMatches.map((item, index) => (
                            <li key={item} role="presentation">
                              <button
                                id={`sport-option-${index}`}
                                type="button"
                                role="option"
                                aria-selected={sportHighlight === index}
                                tabIndex={-1}
                                className={
                                  sportHighlight === index
                                    ? "suggestion-active"
                                    : ""
                                }
                                onMouseEnter={() => setSportHighlight(index)}
                                onMouseDown={(event) => {
                                  event.preventDefault();
                                  setSport(item);
                                  setShowSports(false);
                                  setSportHighlight(-1);
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
                        <p className="no-match">
                          No sport found with that name.
                        </p>
                      )}

                    <p className="field-hint">
                      Click to browse all sports, or start typing to filter.
                    </p>
                  </div>

                  {/* Suburb or postcode search field */}
                  <div className="field">
                    <label htmlFor="suburb">
                      Suburb or postcode <span className="required">*</span>
                    </label>

                    <div className="field-inner">
                      <input
                        id="suburb"
                        type="text"
                        className="input"
                        placeholder="eg: Melbourne CBD or 3000"
                        autoComplete="off"
                        value={suburb}
                        role="combobox"
                        aria-expanded={showSuburbs && suburbMatches.length > 0}
                        aria-controls="suburb-suggestions"
                        aria-autocomplete="list"
                        aria-activedescendant={
                          suburbHighlight >= 0
                            ? `suburb-option-${suburbHighlight}`
                            : undefined
                        }
                        onFocus={() => {
                          setShowSports(false);
                          setSportHighlight(-1);
                        }}
                        onChange={(event) => {
                          setSuburb(event.target.value);
                          setShowSuburbs(true);
                          setSuburbHighlight(-1);
                        }}
                        onKeyDown={handleSuburbKeyDown}
                      />

                      {/* Shows matching suburbs in a dropdown */}
                      {showSuburbs && suburbMatches.length > 0 && (
                        <ul
                          id="suburb-suggestions"
                          className="suggestions"
                          role="listbox"
                          aria-label="Suburb suggestions"
                        >
                          {suburbMatches.map((item, index) => (
                            <li key={item} role="presentation">
                              <button
                                id={`suburb-option-${index}`}
                                type="button"
                                role="option"
                                aria-selected={suburbHighlight === index}
                                tabIndex={-1}
                                className={
                                  suburbHighlight === index
                                    ? "suggestion-active"
                                    : ""
                                }
                                onMouseEnter={() => setSuburbHighlight(index)}
                                onMouseDown={(event) => {
                                  event.preventDefault();
                                  setSuburb(item);
                                  setShowSuburbs(false);
                                  setSuburbHighlight(-1);
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
                      suburbMatches.length === 0 && (
                        <p className="no-match">
                          Try a Greater Melbourne suburb or postcode.
                        </p>
                      )}

                    <p className="field-hint">
                      Enter minimum 3 letters or numbers to search.
                    </p>
                  </div>
                </div>

                {/* Accessibility facility filters */}
                <div className="search-row">
                  <fieldset className="search-group">
                    <legend className="section-title">
                      Choose your access needs:
                    </legend>

                    <div className="checks">
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={toilet}
                          onChange={(event) => setToilet(event.target.checked)}
                        />
                        Accessible toilet
                      </label>

                      <label className="check">
                        <input
                          type="checkbox"
                          checked={parking}
                          onChange={(event) => setParking(event.target.checked)}
                        />
                        Accessible parking
                      </label>

                      <label className="check">
                        <input
                          type="checkbox"
                          checked={stop}
                          onChange={(event) => setStop(event.target.checked)}
                        />
                        Step-free transport stop
                      </label>

                      <label className="check">
                        <input
                          type="checkbox"
                          checked={change}
                          onChange={(event) => setChange(event.target.checked)}
                        />
                        Accessible change facility
                      </label>
                    </div>
                  </fieldset>

                  {/* Distance choices for accessibility facilities */}
                  <fieldset className="search-group">
                    <legend className="section-title">
                      Choose a distance limit:
                    </legend>

                    <div className="distance-options">
                      {distanceBands.map((band) => (
                        <label
                          key={band}
                          className={
                            limit === String(band)
                              ? "distance-option selected-distance"
                              : "distance-option"
                          }
                          onClick={(event) => {
                            // Clicking the selected distance again clears it
                            if (limit === String(band)) {
                              event.preventDefault();
                              setLimit("");
                            }
                          }}
                        >
                          <input
                            type="radio"
                            name="limit"
                            value={band}
                            checked={limit === String(band)}
                            onChange={(event) => setLimit(event.target.value)}
                          />

                          {formatDistanceLabel(band)}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                </div>

                {/* Displays form validation errors */}
                {formError !== "" && (
                  <p className="form-error" role="alert">
                    {formError}
                  </p>
                )}

                {/* Displays errors from the venue search */}
                {searchError !== "" && (
                  <p className="form-error" role="alert">
                    {searchError}
                  </p>
                )}

                {/* Buttons to clear the filters or search for venues */}
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
                    {isSearching ? "Searching…" : "Search venues"}
                  </button>
                </div>
              </form>
            </section>
          )}

          {/* Search results and messages */}
          <div aria-live="polite">
            {results === null ? (
              <section className="results-empty">
                <h2>Nothing searched yet</h2>
                <p>
                  Choose a sport and a location, tick the facilities you need,
                  then select Search venues.
                </p>
              </section>
            ) : (
              <div className="results">
                {/* Reads a summary of the search results aloud */}
                <ReadAloud summary={buildReadAloudSummary()} />

                {/* Shows the number of matching venues */}
                <div className="results-heading">
                  <div>
                    <h2>
                      {results.matched.length === results.total
                        ? `${results.total} venues found`
                        : `${results.matched.length} of ${results.total} venues found`}
                    </h2>

                    <p>
                      {results.searchedSport} venues near{" "}
                      {results.searchedPlace}
                    </p>
                  </div>

                  {results.searchedLimit !== "" && (
                    <span className="filter-badge">
                      {formatDistanceLabel(Number(results.searchedLimit))}{" "}
                      facility limit
                    </span>
                  )}
                </div>

                {/* Message shown when no venues match the filters */}
                {results.matched.length === 0 && (
                  <div className="empty-card">
                    <h3>No matching venues</h3>
                    <p>
                      Try removing an amenity or choosing a bigger distance.
                    </p>
                  </div>
                )}

                {/* Displays the matching venue cards */}
                {results.matched.slice(0, visibleCount).map((venue) => (
                  <VenueCard
                    key={venue.id}
                    venue={venue}
                    limit={results.searchedLimit}
                  />
                ))}

                {/* Loads five more venues when selected */}
                {visibleCount < results.matched.length && (
                  <button
                    type="button"
                    className="view-more-button"
                    onClick={() => setVisibleCount(visibleCount + 5)}
                  >
                    View more venues ({results.matched.length - visibleCount}{" "}
                    more)
                  </button>
                )}

                {/* Explains the facility status colours */}
                {results.matched.length > 0 && (
                  <div className="legend">
                    <div className="legend-item">
                      <span
                        className="legend-box available-box"
                        aria-hidden="true"
                      />
                      Within selected distance
                    </div>

                    <div className="legend-item">
                      <span
                        className="legend-box problem-box"
                        aria-hidden="true"
                      />
                      Outside distance / unavailable
                    </div>

                    <div className="legend-item">
                      <span
                        className="legend-box unknown-box"
                        aria-hidden="true"
                      />
                      No published information
                    </div>
                  </div>
                )}

                {/* Shows venues with missing accessibility information */}
                {results.undocumented.length > 0 && (
                  <div className="missing-section">
                    <button
                      type="button"
                      className="missing-toggle"
                      onClick={() => setShowMissing(!showMissing)}
                    >
                      {results.undocumentedLabel ||
                        "Missing accessibility information"}{" "}
                      ({results.undocumented.length}) {showMissing ? "▲" : "▼"}
                    </button>

                    {showMissing &&
                      results.undocumented.map((venue) => {
                        const missingFacilities =
                          results.selectedAmenities.filter((key) => {
                            const item = venue.amenities[key];
                            return !item || item.state === "none";
                          });

                        return (
                          <div className="missing-venue" key={venue.id}>
                            <strong>{venue.name}</strong>

                            {missingFacilities.map((key) => (
                              <p key={key}>
                                {FACILITY_INFO[key].fullName} information is not
                                available. Please contact the venue to confirm
                                before visiting.
                              </p>
                            ))}
                          </div>
                        );
                      })}
                  </div>
                )}
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Chat assistant for venue and event questions */}
      <Chatbot />
    </div>
  );
}

export default Home;
