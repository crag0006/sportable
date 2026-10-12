import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getCorridor, getVenue } from "../api/venues";
import RouteMap from "../components/RouteMap";
import FacilityCard from "../components/FacilityCard";
import ReadAloud from "../components/ReadAloud";

// Number of facilities shown at a time
const PAGE_SIZE = 6;

// Matches API facility types with the names used in the app
const API_TYPE_TO_KEY = {
  accessible_toilet: "toilet",
  accessible_parking: "parking",
  accessible_transport_stop: "stop",
  accessible_change_facility: "change"
};

function getFacilityKey(facility) {
  return API_TYPE_TO_KEY[facility.type] || facility.type;
}

// Icon names used for each facility type
const TYPE_ICON = {
  toilet: "toilet",
  parking: "parking",
  stop: "transport",
  change: "change"
};

// Default facility names used when a name is not available
const TYPE_LABEL_FALLBACK = {
  toilet: "Accessible toilet",
  parking: "Accessible parking",
  stop: "Accessible transport stop",
  change: "Accessible change facility"
};

// Gets the facility name, address or a default title
function formatFacilityTitle(facility, key) {
  if (facility.name) return facility.name;
  if (facility.address) return facility.address;
  return TYPE_LABEL_FALLBACK[key] || "Accessible facility";
}

// Builds a description using the available facility details
function formatFacilityDescription(facility, key) {
  const parts = [];

  if (facility.name && facility.address && facility.address !== facility.name) {
    parts.push(facility.address);
  }

  if (key === "toilet") {
    if (facility.opening_hours) parts.push(facility.opening_hours);
    if (facility.mlak) parts.push("MLAK key required");
  }

  if (facility.source?.name) {
    parts.push(`Source: ${facility.source.name}`);
  }

  return parts.length > 0
    ? parts.join(" · ")
    : "No further detail published for this facility.";
}

// Creates a short summary of nearby facilities for Read Aloud
function buildReadAloudSummary(venue, corridor) {
  if (!corridor) return [];

  const sentences = [`Getting to ${venue?.name || "this venue"}.`];

  corridor.types.forEach((t) => {
    if (t.status === "found") {
      sentences.push(`${t.count} ${t.label} nearby.`);
    } else {
      sentences.push(`No data recorded for ${t.label}.`);
    }
  });

  // Explains that the map does not show a confirmed accessible route
  sentences.push(
    "This is a straight-line corridor, not a walking route. No dataset confirms the path between these points is step-free."
  );

  return sentences;
}

// Prepares and sorts the facility details for display
function buildFacilityCards(facilities) {
  return (
    [...facilities]
      // Removes facilities recorded as zero metres from the corridor
      .filter((facility) => facility.distance_from_path_m > 0)
      .sort((a, b) => a.distance_from_path_m - b.distance_from_path_m)
      .map((facility) => {
        const key = getFacilityKey(facility);

        return {
          id: `facility-${facility.seq}`,
          icon: TYPE_ICON[key] || "ramp",
          title: formatFacilityTitle(facility, key),
          description: formatFacilityDescription(facility, key),
          state: "within",
          pillText: `${facility.distance_from_path_m} m from the corridor`,
          lat: facility.lat,
          lon: facility.lon,
          type: facility.type
        };
      })
  );
}

export default function DirectionsPage() {
  // Gets the selected venue ID from the page URL
  const { id } = useParams();

  // Stores venue details, map data and page status
  const [venue, setVenue] = useState(null);
  const [corridor, setCorridor] = useState(null);
  const [locationStatus, setLocationStatus] = useState("locating");
  const [manualPlace, setManualPlace] = useState("");
  const [error, setError] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  // Loads the selected venue details from the API
  useEffect(() => {
    getVenue(id)
      .then(setVenue)
      .catch((err) => setError(err.message));
  }, [id]);

  // Gets the corridor and nearby facilities from the API
  function fetchCorridorFrom(fromValue) {
    setError("");
    getCorridor(id, fromValue)
      .then((data) => {
        setCorridor(data);
        setLocationStatus("granted");
        setVisibleCount(PAGE_SIZE);
      })
      .catch((err) => {
        setError(err.message);
      });
  }

  // Gets the user's current location when the page loads
  useEffect(() => {
    if (!navigator.geolocation) {
      setLocationStatus("unsupported");
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const from = `${position.coords.latitude},${position.coords.longitude}`;
        fetchCorridorFrom(from);
      },
      () => {
        setLocationStatus("denied");
      },
      { timeout: 10000 }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Uses the entered suburb or postcode instead of the current location
  function handleManualSubmit(event) {
    event.preventDefault();
    if (!manualPlace.trim()) return;
    fetchCorridorFrom(manualPlace.trim());
  }

  // Prepares the facility cards when corridor data changes
  const facilityCards = useMemo(
    () => (corridor ? buildFacilityCards(corridor.facilities) : []),
    [corridor]
  );

  // Shows only the selected number of facilities
  const visibleFacilities = facilityCards.slice(0, visibleCount);

  // Prepares the text for the Read Aloud feature
  const readAloudSummary = useMemo(
    () => buildReadAloudSummary(venue, corridor),
    [venue, corridor]
  );

  return (
    <div className="venue-page">
      {/* Page header and back link */}
      <header className="venue-topbar">
        <div className="venue-topbar-inner">
          <div className="venue-brand">
            <svg
              width="34"
              height="34"
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
              <div className="venue-brand-name">SportAble</div>
              <div className="venue-brand-tagline">Know more. Play more.</div>
            </div>
          </div>
          <Link className="venue-back-link" to={`/venues/${id}`}>
            ‹ Back to venue details
          </Link>
        </div>
      </header>

      <main className="venue-content">
        {/* Venue name and directions information */}
        <section className="hero-card">
          <p className="eyebrow">Getting there</p>
          <h2>{venue?.name || "This venue"}</h2>
          <p>
            A straight-line corridor from your location to the venue, plus
            accessibility facilities recorded nearby.
          </p>
        </section>

        {/* Message shown while finding the user's location */}
        {locationStatus === "locating" && (
          <section className="section-card">
            <p>Finding your location…</p>
          </section>
        )}

        {/* Manual location search when browser location is unavailable */}
        {(locationStatus === "denied" || locationStatus === "unsupported") &&
          !corridor && (
            <section className="section-card">
              <h3>We couldn't get your location</h3>
              <p>
                {locationStatus === "unsupported"
                  ? "Your browser does not support location access."
                  : "Location access was not granted."}{" "}
                You can type a suburb or postcode instead.
              </p>
              <form
                onSubmit={handleManualSubmit}
                className="manual-location-form"
              >
                <input
                  type="text"
                  value={manualPlace}
                  onChange={(event) => setManualPlace(event.target.value)}
                  placeholder="e.g. Melbourne 3000"
                  aria-label="Suburb or postcode"
                />
                <button type="submit">Use this instead</button>
              </form>
            </section>
          )}

        {/* Shows an error message if the API request fails */}
        {error && (
          <section className="section-card">
            <p>{error}</p>
          </section>
        )}

        {/* Displays the map and facilities when corridor data is available */}
        {corridor && (
          <>
            {/* Read Aloud feature */}
            <section className="section-card">
              <ReadAloud summary={readAloudSummary} />
            </section>

            {/* Summary of nearby accessibility facilities */}
            <section className="section-card">
              <div className="section-head">
                <div>
                  <h3>What's nearby</h3>
                </div>
              </div>
              <div className="types-summary">
                {corridor.types.map((t) => (
                  <div
                    key={t.type}
                    className={`type-summary-card type-summary-card--${t.status}`}
                  >
                    <span>{t.label}</span>
                    <strong>
                      {t.status === "found" ? t.count : "No data"}
                    </strong>
                  </div>
                ))}
              </div>
            </section>

            {/* Map showing the corridor and nearby facilities */}
            <section className="section-card">
              <div className="section-head">
                <div>
                  <h3>Corridor map</h3>
                </div>
              </div>
              <p className="map-note">
                This is a straight-line corridor, not a walking route — no
                dataset confirms the path between these points is step-free.
              </p>
              <RouteMap corridor={corridor} facilities={facilityCards} />
            </section>

            {/* List of nearby accessibility facilities */}
            <section className="section-card">
              <div className="section-head">
                <div>
                  <h3>Nearby accessibility facilities</h3>
                </div>
              </div>
              <div className="facility-list">
                {visibleFacilities.map((facility) => (
                  <FacilityCard key={facility.id} facility={facility} />
                ))}
              </div>

              {/* Loads more facilities when the button is clicked */}
              {visibleCount < facilityCards.length && (
                <button
                  className="view-more-button"
                  type="button"
                  onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
                >
                  View more facilities
                </button>
              )}
            </section>

            {/* Explains what the corridor data can and cannot confirm */}
            <section className="disclaimer-card">
              <h3>What this does and doesn't check</h3>
              {corridor.checked.map((line, index) => (
                <p key={`checked-${index}`}>✓ {line}</p>
              ))}
              {corridor.not_checked.map((line, index) => (
                <p key={`not-checked-${index}`}>✗ {line}</p>
              ))}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
