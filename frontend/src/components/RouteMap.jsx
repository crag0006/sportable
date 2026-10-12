import {
  MapContainer,
  TileLayer,
  Marker,
  Polyline,
  CircleMarker,
  Popup
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Icons and names used for different accessibility facilities
const TYPE_INFO = {
  toilet: { emoji: "🚻", label: "Toilets" },
  parking: { emoji: "🅿", label: "Parking" },
  stop: { emoji: "🚋", label: "Transport stops" },
  change: { emoji: "♿", label: "Change facilities" }
};

// Matches the facility types from the API with the map icons
const API_TYPE_TO_KEY = {
  accessible_toilet: "toilet",
  accessible_parking: "parking",
  accessible_transport_stop: "stop",
  accessible_change_facility: "change"
};

// Default icon used when the facility type is not recognised
const UNKNOWN_TYPE = { emoji: "📍", label: "Facility" };

// Creates a map marker using the facility icon
function createFacilityIcon(type) {
  const { emoji, label } = TYPE_INFO[type] || UNKNOWN_TYPE;

  return L.divIcon({
    className: "facility-marker-icon",
    html: `<div role="img" aria-label="${label}" style="background:#e8f1f8;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;line-height:1;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.35);">${emoji}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13]
  });
}

// Creates map icons for all the known facility types
const facilityIcons = Object.keys(TYPE_INFO).reduce((acc, type) => {
  acc[type] = createFacilityIcon(type);
  return acc;
}, {});

// Creates a general marker for unknown facility types
const unknownFacilityIcon = createFacilityIcon(undefined);

// Creates round markers with letters for the start and venue locations
function createLabelIcon(label, background, accessibleLabel) {
  return L.divIcon({
    className: "route-marker-icon",
    html: `<div role="img" aria-label="${accessibleLabel}" style="background:${background};color:#fff;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.35);">${label}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14]
  });
}

// Markers for the starting point and destination venue
const startIcon = createLabelIcon("S", "#0f4f59", "Starting point");
const venueIcon = createLabelIcon("V", "#c0392b", "Venue");

export default function RouteMap({ corridor, facilities }) {
  // Gets the starting point and venue coordinates from the API response
  const origin = [corridor.origin.latitude, corridor.origin.longitude];
  const venuePoint = [corridor.venue.lat, corridor.venue.lon];

  // Gets the coordinates used to draw the route line
  const pathPoints = corridor.path.coordinates;

  // Sets the map view to include the starting point and venue
  const bounds = [origin, venuePoint];

  return (
    <div className="corridor-map">
      {/* Displays the map using OpenStreetMap */}
      <MapContainer
        bounds={bounds}
        boundsOptions={{ padding: [50, 50] }}
        scrollWheelZoom={false}
        style={{ height: "360px", width: "100%", borderRadius: "12px" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Draws a dashed straight line between the start and venue */}
        <Polyline
          positions={pathPoints}
          pathOptions={{ color: "#0f4f59", weight: 3, dashArray: "8 8" }}
        />

        {/* Starting point marker */}
        <Marker position={origin} icon={startIcon}>
          <Popup>Your starting point</Popup>
        </Marker>

        {/* Destination venue marker */}
        <Marker position={venuePoint} icon={venueIcon}>
          <Popup>{corridor.venue.name}</Popup>
        </Marker>

        {/* Shows facility markers with their names and distances */}
        {facilities.map((facility) => (
          <Marker
            key={facility.id}
            position={[facility.lat, facility.lon]}
            icon={
              facilityIcons[API_TYPE_TO_KEY[facility.type]] ||
              unknownFacilityIcon
            }
          >
            <Popup>
              <strong>{facility.title}</strong>
              <br />
              {facility.pillText}
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      {/* Displays the facility icons and their meanings below the map */}
      <div className="map-legend">
        {Object.entries(TYPE_INFO).map(([type, { emoji, label }]) => (
          <span key={type}>
            <span className="map-legend-glyph" aria-hidden="true">
              {emoji}
            </span>{" "}
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
