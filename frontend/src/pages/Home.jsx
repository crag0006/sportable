import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import TopBar from "../components/TopBar";
import VenueCard, { FACILITY_INFO } from "../components/SearchVenue";
import "./Home.css";
import { getSports, getSuburbs, getConfig, searchVenues } from "../api/venues";

// Reads whatever search we last saved, so if someone leaves this page
// (eg to look at one venue) and comes back, they see the same results
// instead of a blank form. Returns null if nothing was saved yet.
function getSavedSearch() {
  try {
    const saved = sessionStorage.getItem("sportable-last-search");

    if (saved) {
      return JSON.parse(saved);
    }
  } catch {
    // If the saved data is broken for any reason, just ignore it.
  }

  return null;
}

// Turns 1000 into "1km" and 500 into "500m", so the buttons look nice.
function formatDistanceLabel(meters) {
  if (meters >= 1000) {
    return meters / 1000 + "km";
  }

  return meters + "m";
}

function Home() {
  // Sport and suburb lists for the two search boxes. These used to be
  // typed straight into the code. Now we ask the backend for them.
  const [sports, setSports] = useState([]);
  const [suburbs, setSuburbs] = useState([]);

  // The distance choices (250m / 500m / 1km) also come from the backend.
  const [distanceBands, setDistanceBands] = useState([250, 500, 1000]);

  // Search form values
  const [sport, setSport] = useState(() => getSavedSearch()?.sport ?? "");
  const [suburb, setSuburb] = useState(() => getSavedSearch()?.suburb ?? "");

  // Amenity filters
  const [toilet, setToilet] = useState(() => getSavedSearch()?.toilet ?? false);
  const [parking, setParking] = useState(
    () => getSavedSearch()?.parking ?? false
  );
  const [stop, setStop] = useState(() => getSavedSearch()?.stop ?? false);
  const [change, setChange] = useState(() => getSavedSearch()?.change ?? false);

  // Distance filter
  const [limit, setLimit] = useState(() => getSavedSearch()?.limit ?? "");

  // Search suggestions
  const [showSports, setShowSports] = useState(false);
  const [showSuburbs, setShowSuburbs] = useState(false);

  // Search results
  const [results, setResults] = useState(
    () => getSavedSearch()?.results ?? null
  );

  // Whether the search form is open. It starts open, then folds away once
  // a search has run so the results are not pushed down the page.
  const [showForm, setShowForm] = useState(() => !getSavedSearch()?.results);

  // Error message shown when a required field is empty
  const [formError, setFormError] = useState("");

  // Loading and network-error state for the search call
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  // Whether the "missing accessibility information" list is expanded
  const [showMissing, setShowMissing] = useState(false);

  // How many venue cards to show. Starts small; "View more" reveals more.
  const [visibleCount, setVisibleCount] = useState(
    () => getSavedSearch()?.visibleCount ?? 5
  );

  // As soon as the page opens, ask the backend for the sport list,
  // the suburb list, and the distance choices.
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

    getConfig()
      .then((data) => setDistanceBands(data.distanceBandsM))
      .catch(() => setDistanceBands([250, 500, 1000]));
  }, []);

  // Only suggest something once at least 3 characters have been typed
  function findMatches(list, typedText) {
    if (typedText.length < 3) {
      return [];
    }

    return list.filter((item) =>
      item.toLowerCase().includes(typedText.toLowerCase())
    );
  }

  // Runs when someone presses "Search venues". Checks the two required
  // fields first, then asks the backend and shows whatever comes back.
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

    // A plain list of which amenities were ticked, so we can send it to
    // the backend and also show it again later on screen.
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
        limit,
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
        selectedAmenities: selectedAmenities,
      };

      setResults(newResults);
      setVisibleCount(5);

      // Fold the form away so the results are the first thing on screen
      setShowForm(false);

      // Remember this search, so coming back from a venue page shows the
      // same results instead of an empty form.
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
            visibleCount: 5,
          })
        );
      } catch {
        // Not critical if this fails — just skip remembering it.
      }
    } catch (error) {
      setSearchError(
        error.message ||
          "Something went wrong loading venues. Please try again."
      );
    } finally {
      setIsSearching(false);
    }
  }

  // Empties the form and clears the results, so the page goes back to
  // how it looked when it first opened.
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

    try {
      sessionStorage.removeItem("sportable-last-search");
    } catch {
      // Nothing to do if this fails.
    }
  }

  const sportMatches = findMatches(sports, sport);
  const suburbMatches = findMatches(suburbs, suburb);

  // Builds the one-line summary shown on the bar when the form is folded
  // away, eg "Basketball near Preston 3072 · 500m facility limit".
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

  return (
    <div className="search-page">
      {/* Top bar, the same one used on the venue detail page */}
      <TopBar links={[
  { to: "/", label: "Home" },
  { to: "/events", label: "Events" },
]} />

      <main className="search-content">
        {/* Photo banner, matching the venue detail page */}
        <div className="search-banner">
          <div className="search-banner-overlay">
            <p className="search-banner-text">
              No more maybes — every step, mapped out.
            </p>
          </div>
        </div>

        {/* When a search has run and the form is folded away, this bar
            shows what was searched for, with a button to open it again. */}
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
                Edit search
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

        {/* The search form itself */}
        {showForm && (
          <section className="search-card">
            <h1 className="search-title">Find a venue</h1>

            <form onSubmit={handleSearch}>
              {/* Sport and suburb sit side by side to save vertical space */}
              <div className="search-row">
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
              onClick={() => {
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

  {showSports && sport.length >= 3 && sportMatches.length === 0 && (
    <p className="no-match">No sport found with that name.</p>
  )}

  <p className="field-hint">Enter minimum 3 letters to search.</p>
</div>

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

  {showSuburbs && suburb.length >= 3 && suburbMatches.length === 0 && (
    <p className="no-match">
      Try a Greater Melbourne suburb or postcode.
    </p>
  )}

  <p className="field-hint">
    Enter minimum 3 letters or numbers to search.
  </p>
</div>
              </div>

              {/* Amenities and distance, also side by side */}
              <div className="search-row">
                <fieldset className="search-group">
                  <legend className="section-title">Amenities</legend>

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

                <fieldset className="search-group">
                  <legend className="section-title">
                    Preferred distance to a facility
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
        // Clicking the one that is already chosen turns it off again.
        // Radio buttons cannot normally be unselected, so we do it here.
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

              {/* Missing required field */}
              {formError !== "" && (
                <p className="form-error" role="alert">
                  {formError}
                </p>
              )}

              {/* Network problem, kept separate from form validation */}
              {searchError !== "" && (
                <p className="form-error" role="alert">
                  {searchError}
                </p>
              )}

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

        {/* Results. aria-live means a screen reader reads out the new
            count when it changes. */}
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
              <div className="results-heading">
                <div>
                  <h2>
                    {results.matched.length === results.total
                      ? `${results.total} venues found`
                      : `${results.matched.length} of ${results.total} venues found`}
                  </h2>

                  <p>
                    {results.searchedSport} venues near {results.searchedPlace}
                  </p>
                </div>

                {results.searchedLimit !== "" && (
                  <span className="filter-badge">
                    {formatDistanceLabel(Number(results.searchedLimit))} facility
                    limit
                  </span>
                )}
              </div>

              {results.matched.length === 0 && (
                <div className="empty-card">
                  <h3>No matching venues</h3>
                  <p>Try removing an amenity or choosing a bigger distance.</p>
                </div>
              )}

              {results.matched.slice(0, visibleCount).map((venue) => (
                <VenueCard
                  key={venue.id}
                  venue={venue}
                  limit={results.searchedLimit}
                />
              ))}

              {visibleCount < results.matched.length && (
                <button
                  type="button"
                  className="view-more-button"
                  onClick={() => setVisibleCount(visibleCount + 5)}
                >
                  View more venues ({results.matched.length - visibleCount} more)
                </button>
              )}

              {/* What the colours mean */}
              {results.matched.length > 0 && (
                <div className="legend">
                  <div className="legend-item">
                    <span className="legend-box available-box"></span>
                    Within selected distance
                  </div>

                  <div className="legend-item">
                    <span className="legend-box problem-box"></span>
                    Outside distance / unavailable
                  </div>

                  <div className="legend-item">
                    <span className="legend-box unknown-box"></span>
                    No published information
                  </div>
                </div>
              )}

              {/* Venues that match the search but have nothing published
                  for the amenities that were ticked. They are grouped and
                  counted, never dropped. */}
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
  );
}

export default Home;