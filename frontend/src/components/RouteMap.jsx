import { MapContainer, TileLayer, Marker, Polyline, CircleMarker, Popup } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { FacilityIconGlyph } from './Icons'

// Emoji used to mark nearby facilities on the map.
const TYPE_EMOJI = {
  toilet: '🚻',
  parking: '🅿',
  stop: '🚋',
}

function createFacilityIcon(type) {
  const emoji = TYPE_EMOJI[type] || '📍'
  return L.divIcon({
    className: 'facility-marker-icon',
    html: `<div style="background:#e8f1f8;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;line-height:1;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.35);">${emoji}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })
}

const facilityIcons = {
  toilet: createFacilityIcon('toilet'),
  parking: createFacilityIcon('parking'),
  stop: createFacilityIcon('stop'),
}


// Builds a simple round marker with a letter in it (S for start, V for venue),
// so we don't need to fight with Leaflet's default marker image files.
function createLabelIcon(label, background) {
  return L.divIcon({
    className: 'route-marker-icon',
    html: `<div style="background:${background};color:#fff;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.35);">${label}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })
}

const startIcon = createLabelIcon('S', '#0f4f59')
const venueIcon = createLabelIcon('V', '#c0392b')

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
    icon={facilityIcons[facility.type] || facilityIcons.toilet}
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
  <span><span className="legend-icon">🚻</span> Toilets</span>
  <span><span className="legend-icon">🅿</span> Parking</span>
  <span><span className="legend-icon">🚋</span> Transport stops</span>
</div>
    </div>
  )
}