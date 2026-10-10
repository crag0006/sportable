import "./SearchVenue.css";

// Names and icons used for each accessibility facility
export const FACILITY_INFO = {
  toilet: {
    name: "Toilet",
    fullName: "Accessible toilet",
    icon: "🚻"
  },

  parking: {
    name: "Parking",
    fullName: "Accessible parking",
    icon: "🅿"
  },

  stop: {
    name: "Transport",
    fullName: "Step-free transport stop",
    icon: "🚋"
  },

  change: {
    name: "Change facility",
    fullName: "Accessible change facility",
    icon: "♿"
  }
};

// Joins facility names into one sentence using commas and "and"
function joinWithAnd(items) {
  if (items.length <= 1) return items[0] || "";
  if (items.length === 2) return items[0] + " and " + items[1];
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}

// Creates a Google Maps link using the venue's location
function buildMapsUrl(lat, lon) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`;
}

function VenueCard({ venue, limit }) {
  // Gets the list of accessibility facilities for the venue
  const facilityKeys = Object.keys(venue.amenities);

  // Checks whether the venue has latitude and longitude values
  const hasVenueCoordinates =
    venue.latitude !== undefined &&
    venue.latitude !== null &&
    venue.longitude !== undefined &&
    venue.longitude !== null;

  // Checks the facility status and whether it is within the selected distance
  function getState(item) {
    if (!item || item.state === "none") {
      return "unknown";
    }

    if (item.state === "absent") {
      return "absent";
    }

    if (item.state === "confirmed") {
      return "at-venue";
    }

    // Converts the distances into numbers before comparing them
    const facilityDistance = Number(item.distance);
    const selectedLimit = Number(limit);

    if (limit === "" || facilityDistance <= selectedLimit) {
      return "within";
    }

    return "beyond";
  }

  // Returns the message to display for each facility status
  function getText(item, state) {
    if (state === "at-venue") {
      return "At the venue";
    }

    if (state === "within") {
      return item.distance + " m away";
    }

    if (state === "beyond") {
      return item.distance + " m away — beyond your limit";
    }

    if (state === "absent") {
      return "Not available";
    }

    return "No published information — check with the venue";
  }

  // Returns a symbol based on the facility status
  function getStatusSymbol(state) {
    if (state === "at-venue") {
      return "✓";
    }

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

  // Collects the facilities that are recorded as unavailable
  const unavailableFacilities = [];

  facilityKeys.forEach((key) => {
    const item = venue.amenities[key];
    const state = getState(item);

    if (state === "absent") {
      unavailableFacilities.push(key);
    }
  });

  // Opens the selected venue's details page
  function viewVenue() {
    window.location.href = "/venues/" + venue.id;
  }

  // Opens the directions page for the selected venue
  function getDirections() {
    window.location.href = "/venues/" + venue.id + "/directions";
  }

  return (
    <div className="venue-card">
      {/* Venue name, suburb and map link */}
      <div
        className="venue-top"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "12px"
        }}
      >
        <div>
          <h2 className="venue-name">{venue.name}</h2>

          <p className="venue-location">
            {venue.suburb} {venue.postcode}
          </p>
        </div>

        {/* Shows the map link only when venue coordinates are available */}
        {hasVenueCoordinates && (
          <a
            href={buildMapsUrl(venue.latitude, venue.longitude)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Open directions to ${venue.name} in Google Maps`}
            title="Open in Google Maps"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "8px 12px",
              fontFamily: "inherit",
              fontSize: "0.82rem",
              fontWeight: 700,
              color: "#14507a",
              backgroundColor: "#fff",
              border: "1px solid #14507a",
              borderRadius: "999px",
              textDecoration: "none",
              whiteSpace: "nowrap",
              flexShrink: 0
            }}
          >
            <span aria-hidden="true">🧭</span> Map
          </a>
        )}
      </div>

      {/* Lists the sports available at the venue */}
      <p className="sports-heading">Other sports offered here:</p>
      <div className="sport-chips">
        {venue.sports.map((venueSport) => (
          <span className="sport-chip" key={venueSport}>
            {venueSport}
          </span>
        ))}
      </div>

      {/* Shows the venue's surface information */}
      <p className="surface-text">
        <strong>Surface:</strong> {venue.surface || "Information Not available"}
      </p>

      <div className="access-heading">Accessibility</div>

      {/* Displays each facility with its icon, distance and status */}
      <div className="amenity-grid">
        {facilityKeys.map((key) => {
          const item = venue.amenities[key];

          const state = getState(item);

          return (
            <div key={key} className={"amenity-box amenity-" + state}>
              <span className="facility-icon" aria-hidden="true">
                {FACILITY_INFO[key].icon}
              </span>

              <div className="amenity-content">
                <strong>{FACILITY_INFO[key].name}</strong>

                <p>{getText(item, state)}</p>
              </div>

              <span
                className={"status-symbol status-" + state}
                aria-label={state}
              >
                {getStatusSymbol(state)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Shows a message when one or more facilities are unavailable */}
      {unavailableFacilities.length > 0 && (
        <p className="facility-message unavailable-message">
          {joinWithAnd(
            unavailableFacilities.map((key) => FACILITY_INFO[key].fullName)
          )}{" "}
          {unavailableFacilities.length > 1 ? "are" : "is"} recorded as not
          available. Please contact the venue to confirm before visiting.
        </p>
      )}

      {/* Buttons to view venue details or get directions */}
      <div className="card-buttons">
        <button type="button" className="view-button" onClick={viewVenue}>
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
