import "./SearchVenue.css";

export const FACILITY_INFO = {
  toilet: {
    name: "Toilet",
    fullName: "Accessible toilet",
    icon: "🚻",
  },

  parking: {
    name: "Parking",
    fullName: "Accessible parking",
    icon: "🅿",
  },

  stop: {
    name: "Transport",
    fullName: "Step-free transport stop",
    icon: "🚋",
  },

  change: {
    name: "Change facility",
    fullName: "Accessible change facility",
    icon: "♿",
  },
};

function VenueCard({ venue, limit }) {
  const facilityKeys = Object.keys(
    venue.amenities
  );

  // Check the status of one facility
  function getState(item) {
    if (!item || item.state === "none") {
      return "unknown";
    }

    if (item.state === "absent") {
      return "absent";
    }

    const facilityDistance = Number(
      item.distance
    );

    const selectedLimit = Number(limit);

    if (
      limit === "" ||
      facilityDistance <= selectedLimit
    ) {
      return "within";
    }

    return "beyond";
  }

  // Text shown under each facility
  function getText(item, state) {
    if (state === "within") {
      return item.distance + " m away";
    }

    if (state === "beyond") {
      return (
        item.distance +
        " m away — beyond your limit"
      );
    }

    if (state === "absent") {
      return "Not available";
    }

    return "No published information — check with the venue";
  }

  // Symbol for the facility status
  function getStatusSymbol(state) {
    if (state === "within") {
      return "✓";
    }

    if (state === "beyond") {
      return "!";
    }

    if (state === "absent") {
      return "✕";
    }

    return "?";
  }

  // Find missing and unavailable facilities
 const unavailableFacilities = [];

facilityKeys.forEach((key) => {
  const item = venue.amenities[key];
  const state = getState(item);

  if (state === "absent") {
    unavailableFacilities.push(key);
  }
});

  // View venue page
  function viewVenue() {
    window.location.href =
      "/venues/" + venue.id;
  }

  // Directions page
  function getDirections() {
    window.location.href =
      "/venues/" +
      venue.id +
      "/directions";
  }

  return (
    <div className="venue-card">
      {/* Venue name and distance */}
      <div className="venue-top">
        <div>
          <h2 className="venue-name">
            {venue.name}
          </h2>

          <p className="venue-location">
            {venue.suburb} {venue.postcode}
          </p>
        </div>

       <div className="venue-distance">
            <span className="distance-label">Venue distance</span>
            <strong>{venue.distance} km away</strong>
                  </div>
      </div>

      {/* Sports */}
      <div className="sport-chips">
        {venue.sports.map((venueSport) => (
          <span
            className="sport-chip"
            key={venueSport}
          >
            {venueSport}
          </span>
        ))}
      </div>

      {/* Surface */}
      <p className="surface-text">
        <strong>Surface:</strong>{" "}
        {venue.surface}
      </p>

      <div className="access-heading">
        Accessibility
      </div>

      {/* Facility cards */}
      <div className="amenity-grid">
        {facilityKeys.map((key) => {
          const item =
            venue.amenities[key];

          const state = getState(item);

          return (
            <div
              key={key}
              className={
                "amenity-box amenity-" +
                state
              }
            >
              <span
                className="facility-icon"
                aria-hidden="true"
              >
                {FACILITY_INFO[key].icon}
              </span>

              <div className="amenity-content">
                <strong>
                  {FACILITY_INFO[key].name}
                </strong>

                <p>
                  {getText(item, state)}
                </p>
              </div>

              <span
                className={
                  "status-symbol status-" +
                  state
                }
                aria-label={state}
              >
                {getStatusSymbol(state)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Facility unavailable */}
      {unavailableFacilities.map((key) => (
        <p
          className="facility-message unavailable-message"
          key={key}
        >
          {FACILITY_INFO[key].fullName} is
          recorded as not available. Please
          contact the venue to confirm before
          visiting.
        </p>
      ))}

      {/* Buttons */}
      <div className="card-buttons">
        <button
          type="button"
          className="view-button"
          onClick={viewVenue}
        >
          View venue
        </button>

        <button
          type="button"
          className="direction-button"
          onClick={getDirections}
        >
          Get directions
        </button>
      </div>
    </div>
  );
}

export default VenueCard;