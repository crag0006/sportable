const ICON_EMOJI = {
  toilet: "🚻",
  parking: "🅿",
  transport: "🚋",
  change: "♿",
};

// Builds a Google Maps "directions to" link. Leaving the origin out means
// Google Maps uses the visitor's current location automatically — this is
// the exact facility's own coordinates (from the corridor/directions API),
// not just the venue, so it routes to the right place even for a facility
// that isn't at the venue itself.
function buildMapsUrl(lat, lon) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`;
}

function FacilityCard({ facility }) {
  // "state" decides the colour: green = good news, red = bad news,
  // grey = nothing published.
  const state = facility.state || "unknown";

  const hasCoordinates =
    facility.lat !== undefined &&
    facility.lat !== null &&
    facility.lon !== undefined &&
    facility.lon !== null;

  return (
    <article className={`facility-card facility-${state}`}>
      <div className="facility-icon">
        {ICON_EMOJI[facility.icon] || "📍"}
      </div>

      <div className="facility-body">
        <div className="facility-top">
          <div>
            <h3>{facility.title}</h3>
            <p>{facility.description}</p>
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-end",
              gap: "6px",
            }}
          >
            <div className={`distance-pill distance-pill--${state}`}>
              {facility.pillText || facility.distance || "—"}
            </div>

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
                  whiteSpace: "nowrap",
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
