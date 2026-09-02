import { Link } from 'react-router-dom'

function buildMiniMapGeometry(mapData) {
  const coordinates = mapData?.coordinates ?? []
  const facilityPoints = mapData?.facilityPoints ?? []
  const allPoints = [
    ...coordinates.map(([lat, lon]) => ({ lat, lon })),
    ...facilityPoints.map((point) => ({ lat: point.lat, lon: point.lon })),
  ]

  if (allPoints.length === 0) {
    return null
  }

  const lats = allPoints.map((point) => point.lat)
  const lons = allPoints.map((point) => point.lon)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const latRange = maxLat - minLat || 0.01
  const lonRange = maxLon - minLon || 0.01

  function project(lat, lon) {
    const x = 14 + ((lon - minLon) / lonRange) * 72
    const y = 84 - ((lat - minLat) / latRange) * 68
    return { x: Number(x.toFixed(2)), y: Number(y.toFixed(2)) }
  }

  return {
    path: coordinates.map(([lat, lon]) => project(lat, lon)),
    facilityPoints: facilityPoints.map((point) => ({
      ...point,
      ...project(point.lat, point.lon),
    })),
  }
}

export default function MiniMapLinkCard({ label, caption, linkLabel, to, mapData }) {
  const geometry = buildMiniMapGeometry(mapData)

  return (
    <section className="mini-note-card">
      <span className="side-label">{label}</span>

      <Link className="mini-map-anchor" to={to}>
        <div className="mini-map-panel" aria-label="Linked route map preview">
          <div className="mini-map-grid" />
          <div className="mini-road one" />
          <div className="mini-road two" />
          <div className="mini-road three" />
          {geometry ? (
            <svg
              viewBox="0 0 100 100"
              aria-hidden="true"
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', zIndex: 2 }}
            >
              {geometry.path.length >= 2 ? (
                <polyline
                  points={geometry.path.map((point) => `${point.x},${point.y}`).join(' ')}
                  fill="none"
                  stroke="#14507a"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ) : null}
              {geometry.facilityPoints.map((point) => (
                <circle
                  key={`${point.type}-${point.seq}`}
                  cx={point.x}
                  cy={point.y}
                  r="2.6"
                  fill="#ffbf47"
                  stroke="#0c1c2d"
                  strokeWidth="1.2"
                />
              ))}
              {geometry.path[0] ? <circle cx={geometry.path[0].x} cy={geometry.path[0].y} r="4" fill="#0c1c2d" /> : null}
              {geometry.path.at(-1) ? <circle cx={geometry.path.at(-1).x} cy={geometry.path.at(-1).y} r="4" fill="#14507a" /> : null}
            </svg>
          ) : (
            <>
              <div className="mini-route" />
              <div className="mini-marker start">S</div>
              <div className="mini-marker end">V</div>
            </>
          )}
        </div>

        <div className="mini-map-caption">
          <span>{caption}</span>
          <span className="mini-map-link">{linkLabel}</span>
        </div>
      </Link>
    </section>
  )
}
