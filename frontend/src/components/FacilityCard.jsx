// Icons used for different accessibility facilities
const ICON_EMOJI = {
  toilet: "🚻",
  parking: "🅿",
  transport: "🚋",
  change: "♿"
};

// Creates a Google Maps directions link using the facility's location
function buildMapsUrl(lat, lon) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`;
}

function FacilityCard({ facility }) {
  // Gets the facility status, or uses unknown if no status is available
  const state = facility.state || "unknown";

  // Checks whether the facility's location coordinates are available
  const hasCoordinates =
    facility.lat !== undefined &&
    facility.lat !== null &&
    facility.lon !== undefined &&
    facility.lon !== null;

  return (
    <article className={`facility-card facility-${state}`}>
      {/* Facility icon */}
      <div className="facility-icon">{ICON_EMOJI[facility.icon] || "📍"}</div>

      <div className="facility-body">
        <div className="facility-top">
          {/* Facility name and description */}
          <div>
            <h3>{facility.title}</h3>
            <p>{facility.description}</p>
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-end",
              gap: "6px"
            }}
          >
            {/* Shows the facility distance or status */}
            <div className={`distance-pill distance-pill--${state}`}>
              {facility.pillText || facility.distance || "—"}
            </div>

            {/* Shows the map link when facility coordinates are available */}
            {hasCoordinates && (
              <a
                href={buildMapsUrl(facility.lat, facility.lon)}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Open directions to ${facility.title} in Google Maps`}
                title="Open in Google Maps"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                  fontFamily: "inherit",
                  fontSize: "0.78rem",
                  fontWeight: 700,
                  color: "#14507a",
                  textDecoration: "none",
                  whiteSpace: "nowrap"
                }}
              >
                <span aria-hidden="true">🧭</span> Map
              </a>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

export default FacilityCard;
