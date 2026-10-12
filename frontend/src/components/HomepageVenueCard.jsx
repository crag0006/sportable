import { useNavigate } from "react-router-dom";
import { FACILITY_INFO } from "../data/homepageVenues";

export default function HomepageVenueCard({ venue, limit }) {
  const navigate = useNavigate();

  // Gets the list of accessibility facilities for the venue
  const facilityKeys = Object.keys(venue.amenities);

  // Checks the facility status and selected distance limit
  function getState(item) {
    if (!item || item.state === "none") {
      return "unknown";
    }

    if (item.state === "absent") {
      return "absent";
    }

    const facilityDistance = Number(item.distance);
    const selectedLimit = Number(limit);

    if (limit === "" || facilityDistance <= selectedLimit) {
      return "within";
    }

    return "beyond";
  }

  // Returns the message to display for each facility status
  function getText(item, state) {
    if (state === "within") {
      return `${item.distance} m away`;
    }

    if (state === "beyond") {
      return `${item.distance} m away — beyond your limit`;
    }

    if (state === "absent") {
      return "Not available";
    }

    return "No published information";
  }

  // Returns a symbol based on the facility status
  function getStatusSymbol(state) {
    if (state === "within") return "✓";
    if (state === "beyond") return "!";
    if (state === "absent") return "✕";
    return "?";
  }

  // Stores facilities with missing or unavailable information
  const missingFacilities = [];
  const unavailableFacilities = [];

  // Checks the status of each accessibility facility
  facilityKeys.forEach((key) => {
    const item = venue.amenities[key];
    const state = getState(item);

    if (state === "unknown") {
      missingFacilities.push(key);
    }

    if (state === "absent") {
      unavailableFacilities.push(key);
    }
  });

  return (
    <div className="home-venue-card">
      {/* Venue name, suburb and distance */}
      <div className="home-venue-top">
        <div>
          <h2 className="home-venue-name">{venue.name}</h2>
          <p className="home-venue-location">
            {venue.suburb} {venue.postcode}
          </p>
        </div>

        <div className="home-venue-distance">
          <span className="home-distance-label">Venue distance</span>
          <strong>{venue.distance} km away</strong>
        </div>
      </div>

      {/* Sports available at the venue */}
      <div className="home-sport-chips">
        {venue.sports.map((venueSport) => (
          <span className="home-sport-chip" key={venueSport}>
            {venueSport}
          </span>
        ))}
      </div>

      {/* Venue surface information */}
      <p className="home-surface-text">
        <strong>Surface:</strong> {venue.surface}
      </p>

      <div className="home-access-heading">Accessibility</div>

      {/* Displays each facility with its icon, distance and status */}
      <div className="home-amenity-grid">
        {facilityKeys.map((key) => {
          const item = venue.amenities[key];
          const state = getState(item);

          return (
            <div key={key} className={`home-amenity-box home-amenity-${state}`}>
              <span className="home-facility-icon" aria-hidden="true">
                {FACILITY_INFO[key].icon}
              </span>

              <div className="home-amenity-content">
                <strong>{FACILITY_INFO[key].name}</strong>
                <p>{getText(item, state)}</p>
              </div>

              <span
                className={`home-status-symbol home-status-${state}`}
                aria-label={state}
              >
                {getStatusSymbol(state)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Shows a message for facilities with missing information */}
      {missingFacilities.map((key) => (
        <p className="home-facility-message" key={key}>
          {FACILITY_INFO[key].fullName} information is not available. Please
          contact the venue to confirm before visiting.
        </p>
      ))}

      {/* Shows a message for facilities recorded as unavailable */}
      {unavailableFacilities.map((key) => (
        <p className="home-facility-message home-unavailable-message" key={key}>
          {FACILITY_INFO[key].fullName} is recorded as not available. Please
          contact the venue to confirm before visiting.
        </p>
      ))}

      {/* Buttons to view the venue or get directions */}
      <div className="home-card-buttons">
        <button
          type="button"
          className="home-view-button"
          onClick={() => navigate(`/venues/${venue.id}`)}
        >
          View venue
        </button>

        <button
          type="button"
          className="home-direction-button"
          onClick={() => navigate(`/venues/${venue.id}/directions`)}
        >
          Get directions
        </button>
      </div>
    </div>
  );
}
