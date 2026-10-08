import { MapContainer, TileLayer, Marker, Polyline, CircleMarker, Popup } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// Single source of truth for facility marker types: emoji + accessible label.
// The legend below is generated from this object, so it can never drift out
// of sync with what the map actually plots. Add new facility types here only.
const TYPE_INFO = {
  toilet: { emoji: '🚻', label: 'Toilets' },
  parking: { emoji: '🅿', label: 'Parking' },
  stop: { emoji: '🚋', label: 'Transport stops' },
  change: { emoji: '♿', label: 'Change facilities' },
}

// Your API (see API_CONTRACT.md §2/§10) sends facility.type as the long DB
// enum value, not the short keys above — the same mapping Events.jsx already
// needed via EVENT_FACILITY_TYPE_TO_KEY. Without this, facility.type never
// matches a TYPE_INFO key and every marker falls back to the generic pin.
const API_TYPE_TO_KEY = {
  accessible_toilet: 'toilet',
  accessible_parking: 'parking',
  accessible_transport_stop: 'stop',
  accessible_change_facility: 'change',
}

// Fallback for any facility type not listed in TYPE_INFO — a generic pin,
// never a specific facility icon, so an unrecognised type is never mislabeled
// as (say) a toilet.
const UNKNOWN_TYPE = { emoji: '📍', label: 'Facility' }

function createFacilityIcon(type) {
  const { emoji, label } = TYPE_INFO[type] || UNKNOWN_TYPE
  return L.divIcon({
    className: 'facility-marker-icon',
    html: `<div role="img" aria-label="${label}" style="background:#e8f1f8;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;line-height:1;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.35);">${emoji}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })
}

const facilityIcons = Object.keys(TYPE_INFO).reduce((acc, type) => {
  acc[type] = createFacilityIcon(type)
  return acc
}, {})

// Used when a facility's type isn't one of the known TYPE_INFO keys, so it
// still renders as a distinct, honestly-labeled marker instead of silently
// reusing (and misrepresenting) an unrelated icon.
const unknownFacilityIcon = createFacilityIcon(undefined)

// Builds a simple round marker with a letter in it (S for start, V for venue),
// so we don't need to fight with Leaflet's default marker image files.
function createLabelIcon(label, background, accessibleLabel) {
  return L.divIcon({
    className: 'route-marker-icon',
    html: `<div role="img" aria-label="${accessibleLabel}" style="background:${background};color:#fff;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.35);">${label}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })
}

const startIcon = createLabelIcon('S', '#0f4f59', 'Starting point')
const venueIcon = createLabelIcon('V', '#c0392b', 'Venue')

// corridor: the raw response from GET /venues/{id}/corridor
// facilities: the same list, already formatted for FacilityCard, so we can reuse title/pillText for map popups
export default function RouteMap({ corridor, facilities }) {
  const origin = [corridor.origin.latitude, corridor.origin.longitude]
  const venuePoint = [corridor.venue.lat, corridor.venue.lon]
  const pathPoints = corridor.path.coordinates // already [lat, lon] pairs, no conversion needed
  const bounds = [origin, venuePoint]

  return (
    <div className="corridor-map">
      <MapContainer
        bounds={bounds}
        boundsOptions={{ padding: [50, 50] }}
        scrollWheelZoom={false}
        style={{ height: '360px', width: '100%', borderRadius: '12px' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* This is a straight-line corridor, not a walked or driven route — dashed line makes that visually clear */}
        <Polyline positions={pathPoints} pathOptions={{ color: '#0f4f59', weight: 3, dashArray: '8 8' }} />

        <Marker position={origin} icon={startIcon}>
          <Popup>Your starting point</Popup>
        </Marker>

        <Marker position={venuePoint} icon={venueIcon}>
          <Popup>{corridor.venue.name}</Popup>
        </Marker>

        {facilities.map((facility) => (
          <Marker
            key={facility.id}
            position={[facility.lat, facility.lon]}
            icon={facilityIcons[API_TYPE_TO_KEY[facility.type]] || unknownFacilityIcon}
          >
            <Popup>
              <strong>{facility.title}</strong>
              <br />
              {facility.pillText}
            </Popup>
          </Marker>
        ))}

      </MapContainer>

      <div className="map-legend">
        {Object.entries(TYPE_INFO).map(([type, { emoji, label }]) => (
          <span key={type}>
            {/* Renamed from "legend-icon" — that class name already exists
                elsewhere in the stylesheet with its own background/sizing
                rules built for a different icon mechanism, and it was
                silently hiding this emoji. "map-legend-glyph" is unique. */}
            <span className="map-legend-glyph" aria-hidden="true">{emoji}</span> {label}
          </span>
        ))}
      </div>
    </div>
  )
}
