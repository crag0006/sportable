import { useState } from "react";
import VenueCard, { FACILITY_INFO } from "../components/SearchVenue";
import "./Home.css";
import { VENUES, PLACE_NAMES } from "../data/Venues";


const SPORTS = [
  "Badminton",
  "Basketball",
  "Netball",
  "Swimming",
  "Tennis",
];

const SUBURBS = [
  "Melbourne CBD 3000",
  "Carlton 3053",
  "Fitzroy 3065",
  "North Melbourne 3051",
  "Preston 3072",
  "Kensington 3031",
];

function Home() {
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

  // Error message
  const [formError, setFormError] = useState("");

  // Find suggestions after 3 characters
  function findMatches(list, typedText) {
    if (typedText.length < 3) {
      return [];
    }

    return list.filter((item) =>
      item.toLowerCase().includes(typedText.toLowerCase())
    );
  }

  // Check the status of one facility
  function getAmenityState(amenity) {
    if (!amenity || amenity.state === "none") {
      return "unknown";
    }

    if (amenity.state === "absent") {
      return "absent";
    }

    const facilityDistance = Number(amenity.distance);
    const selectedLimit = Number(limit);

    if (limit === "" || facilityDistance <= selectedLimit) {
      return "within";
    }

    return "beyond";
  }

  // Search venues
  function handleSearch(event) {
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

    const postcode = suburb.slice(-4);

    // Get venues that offer the selected sport
    const sportVenues = VENUES.filter((venue) =>
      venue.sports.includes(sport)
    );

    // Store selected amenities
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

    const matchedVenues = [];
    const missingInfoVenues = [];

    // Check each venue
    sportVenues.forEach((venue) => {
      let allMatch = true;
      let hasMissingInfo = false;

      selectedAmenities.forEach((key) => {
        const amenity = venue.amenities[key];
        const state = getAmenityState(amenity);

        if (state !== "within") {
          allMatch = false;
        }

        if (state === "unknown") {
          hasMissingInfo = true;
        }
      });

      if (allMatch) {
        matchedVenues.push(venue);
      } else if (hasMissingInfo) {
        missingInfoVenues.push(venue);
      }
    });

    // Show closest venues first
    matchedVenues.sort((a, b) => a.distance - b.distance);

    // Save the values used for this search
    setResults({
      total: sportVenues.length,
      matched: matchedVenues,
      undocumented: missingInfoVenues,
      place: PLACE_NAMES[postcode] || suburb,
      searchedSport: sport,
      searchedLimit: limit,
      selectedAmenities: selectedAmenities,
    });
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
    setShowSports(false);
    setShowSuburbs(false);

    // Keep current search results
  }

  const sportMatches = findMatches(SPORTS, sport);
  const suburbMatches = findMatches(SUBURBS, suburb);

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

          {/* Distance */}
          <h2 className="section-title">
            Distance to a facility
          </h2>

          <div className="distance-options">
            <label
              className={
                limit === "250"
                  ? "distance-option selected-distance"
                  : "distance-option"
              }
            >
              <input
                type="radio"
                name="limit"
                value="250"
                checked={limit === "250"}
                onChange={(event) =>
                  setLimit(event.target.value)
                }
              />
              250 m
            </label>

            <label
              className={
                limit === "500"
                  ? "distance-option selected-distance"
                  : "distance-option"
              }
            >
              <input
                type="radio"
                name="limit"
                value="500"
                checked={limit === "500"}
                onChange={(event) =>
                  setLimit(event.target.value)
                }
              />
              500 m
            </label>

            <label
              className={
                limit === "1000"
                  ? "distance-option selected-distance"
                  : "distance-option"
              }
            >
              <input
                type="radio"
                name="limit"
                value="1000"
                checked={limit === "1000"}
                onChange={(event) =>
                  setLimit(event.target.value)
                }
              />
              1 km
            </label>
          </div>

          {/* Error */}
          {formError !== "" && (
            <p className="form-error" role="alert">
              {formError}
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
            >
              Search venues
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
                  {results.searchedLimit === "1000"
                    ? "1 km"
                    : results.searchedLimit + " m"}{" "}
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
                  Missing accessibility information
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