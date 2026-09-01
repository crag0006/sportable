import { useState, useEffect } from "react";
import VenueCard, { FACILITY_INFO } from "../components/SearchVenue";
import "./Home.css";
import { getSports, getSuburbs, getConfig, searchVenues } from "../api/venues";

// We no longer import fake data from "../data/Venues" — this page now
// asks the real backend for everything instead. You can delete
// src/data/Venues.js once you've tested this against the real API.

// Turns 1000 into "1km" and 500 into "500m", so the buttons look nice.
function formatDistanceLabel(meters) {
  if (meters >= 1000) {
    return meters / 1000 + "km";
  }

  return meters + "m";
}

function Home() {
  // Sport & suburb lists for the two dropdowns. These used to be typed
  // straight into the code. Now we ask the backend for them instead.
  const [sports, setSports] = useState([]);
  const [suburbs, setSuburbs] = useState([]);

  // The distance choices (250m / 500m / 1km) also come from the backend
  // now, instead of being hardcoded here.
  const [distanceBands, setDistanceBands] = useState([250, 500, 1000]); // fallback until backend is live

  // Search form values
  const [sport, setSport] = useState("");
  const [suburb, setSuburb] = useState("");

  // Amenity filters
  const [toilet, setToilet] = useState(false);
  const [parking, setParking] = useState(false);
  const [stop, setStop] = useState(false);
  const [change, setChange] = useState(false);

  // Distance filter
  const [limit, setLimit] = useState("");

  // Search suggestions
  const [showSports, setShowSports] = useState(false);
  const [showSuburbs, setShowSuburbs] = useState(false);

  // Search results
  const [results, setResults] = useState(null);

  // Error message (form validation)
  const [formError, setFormError] = useState("");

  // Loading / network-error state for the search call
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  // As soon as the page opens, ask the backend for the sport list, the
  // suburb list, and the distance choices.
  useEffect(() => {
    getSports()
      .then((data) => setSports(data))
      .catch(() => setSports(["Badminton", "Basketball", "Netball", "Swimming", "Tennis"]));

    getSuburbs()
      .then((data) => setSuburbs(data))
      .catch(() => setSuburbs(["Melbourne", "Carlton", "Fitzroy", "North Melbourne", "Preston", "Kensington"]));

    getConfig()
      .then((data) => setDistanceBands(data.distanceBandsM))
      .catch(() => setDistanceBands([250, 500, 1000])); // fallback until backend is live
  }, []);

  // Find suggestions after 3 characters
  function findMatches(list, typedText) {
    if (typedText.length < 3) {
      return [];
    }

    return list.filter((item) =>
      item.toLowerCase().includes(typedText.toLowerCase())
    );
  }

  // Runs when someone clicks "Search venues". It used to search through
  // a list of fake venues by hand, working out which ones matched.
  // Now it just asks the backend and shows whatever comes back —
  // the backend does all that matching work now.
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

    // Make a plain list of which amenities were ticked, so we can send
    // it to the backend and also show it later on screen.
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

      setResults({
        total: data.total,
        matched: data.matched,
        undocumented: data.undocumented,
        undocumentedLabel: data.undocumentedLabel,
        place: data.place,
        searchedSport: sport,
        // The backend tells us exactly which distance it used, even if
        // the user didn't pick one, so we always show the real number.
        searchedLimit: data.distanceLimitM ? String(data.distanceLimitM) : "",
        selectedAmenities: selectedAmenities,
      });
    } catch (error) {
      setSearchError(
        error.message || "Something went wrong loading venues. Please try again."
      );
    } finally {
      setIsSearching(false);
    }
  }

  // Clear the form only
  function handleClear() {
    setSport("");
    setSuburb("");

    setToilet(false);
    setParking(false);
    setStop(false);
    setChange(false);

    setLimit("");

    setFormError("");
    setSearchError("");
    setShowSports(false);
    setShowSuburbs(false);

    // Keep current search results
  }

  const sportMatches = findMatches(sports, sport);
  const suburbMatches = findMatches(suburbs, suburb);

  return (
    <div className="split">
      {/* Left side */}
      <div className="split-left">
        <div className="hero-brand">
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="4" r="2" />
            <path d="M11 8v6h5l3 6" />
            <path d="M15.5 14a5.5 5.5 0 1 1-6-5.48" />
          </svg>

          <div>
            <div className="hero-name">SportAble</div>
            <div className="hero-tagline">
              Know more. Play more.
            </div>
          </div>
        </div>

        <h1 className="hero-headline">
          No limits. Just possibilities.
        </h1>

        {/* Search form */}
        <form className="panel" onSubmit={handleSearch}>
          {/* Sport */}
          <div className="field">
            <label htmlFor="sport">
              Sport <span className="required">*</span>
            </label>

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

            {showSports &&
              sport.length >= 3 &&
              sportMatches.length === 0 && (
                <p className="no-match">
                  No sport found with that name.
                </p>
              )}
          </div>

          {/* Suburb */}
          <div className="field second-field">
            <label htmlFor="suburb">
              Suburb or postcode{" "}
              <span className="required">*</span>
            </label>

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

            {showSuburbs &&
              suburb.length >= 3 &&
              suburbMatches.length === 0 && (
                <p className="no-match">
                  Try a Greater Melbourne suburb or postcode.
                </p>
              )}
          </div>

          {/* Amenities */}
          <h2 className="section-title">
            Amenities
          </h2>

          <div className="checks">
            <label className="check">
              <input
                type="checkbox"
                checked={toilet}
                onChange={(event) =>
                  setToilet(event.target.checked)
                }
              />
              Accessible toilet
            </label>

            <label className="check">
              <input
                type="checkbox"
                checked={parking}
                onChange={(event) =>
                  setParking(event.target.checked)
                }
              />
              Accessible parking
            </label>

            <label className="check">
              <input
                type="checkbox"
                checked={stop}
                onChange={(event) =>
                  setStop(event.target.checked)
                }
              />
              Step-free transport stop
            </label>

            <label className="check">
              <input
                type="checkbox"
                checked={change}
                onChange={(event) =>
                  setChange(event.target.checked)
                }
              />
              Accessible change facility
            </label>
          </div>

          {/* Distance — options now come from GET /config, not hardcoded */}
          <h2 className="section-title">
            Distance to a facility
          </h2>

          <div className="distance-options">
            {distanceBands.map((band) => (
              <label
                key={band}
                className={
                  limit === String(band)
                    ? "distance-option selected-distance"
                    : "distance-option"
                }
              >
                <input
                  type="radio"
                  name="limit"
                  value={band}
                  checked={limit === String(band)}
                  onChange={(event) =>
                    setLimit(event.target.value)
                  }
                />
                {formatDistanceLabel(band)}
              </label>
            ))}
          </div>

          {/* Error */}
          {formError !== "" && (
            <p className="form-error" role="alert">
              {formError}
            </p>
          )}

          {/* Network/search error, separate from form validation */}
          {searchError !== "" && (
            <p className="form-error" role="alert">
              {searchError}
            </p>
          )}

          {/* Buttons */}
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
      </div>

      {/* Right side */}
      <div className="split-right" aria-live="polite">
        {results === null ? (
          <div className="photo"></div>
        ) : (
          <div className="results">
            {/* Result heading */}
            <div className="results-heading">
              <div>
                <h2>
                  {results.matched.length} of{" "}
                  {results.total} venues found
                </h2>

                <p>
                  {results.searchedSport} near{" "}
                  {results.place}
                </p>
              </div>

              {results.searchedLimit !== "" && (
                <span className="filter-badge">
                  {formatDistanceLabel(Number(results.searchedLimit))}{" "}
                  facility limit
                </span>
              )}
            </div>

            {/* No matches */}
            {results.matched.length === 0 && (
              <div className="empty-card">
                <h3>No matching venues</h3>

                <p>
                  Try removing an amenity or choosing a
                  bigger distance.
                </p>
              </div>
            )}

            {/* Venue cards */}
            {results.matched.map((venue) => (
              <VenueCard
                key={venue.id}
                venue={venue}
                limit={results.searchedLimit}
              />
            ))}

            {/* Colour guide */}
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

            {/* Missing selected information */}
            {results.undocumented.length > 0 && (
              <div className="missing-section">
                <h3>
                  {results.undocumentedLabel ||
                    "Missing accessibility information"}
                </h3>

                {results.undocumented.map((venue) => {
                  const missingFacilities =
                    results.selectedAmenities.filter(
                      (key) => {
                        const item =
                          venue.amenities[key];

                        return (
                          !item ||
                          item.state === "none"
                        );
                      }
                    );

                  return (
                    <div
                      className="missing-venue"
                      key={venue.id}
                    >
                      <strong>{venue.name}</strong>

                      {missingFacilities.map((key) => (
                        <p key={key}>
                          {
                            FACILITY_INFO[key]
                              .fullName
                          }{" "}
                          information is not
                          available. Please contact
                          the venue to confirm before
                          visiting.
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
    </div>
  );
}

export default Home;