import { useMemo, useState } from 'react'
import DirectionsFacilityItem from './DirectionsFacilityItem'
import { LocateIcon, ZoomInIcon, ZoomOutIcon } from './Icons'

function buildMapGeometry(mapData) {
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
    const x = 12 + ((lon - minLon) / lonRange) * 76
    const y = 88 - ((lat - minLat) / latRange) * 76
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

export default function StaticRouteMap({ mapData, facilities, sectionTitle, sectionBody }) {
  const [zoomLevel, setZoomLevel] = useState(1)
  const [isLocated, setIsLocated] = useState(false)
  const summaryCards = mapData?.summaryCards ?? []
  const callouts = mapData?.callouts ?? []
  const facilityItems = facilities ?? []
  const geometry = useMemo(() => buildMapGeometry(mapData), [mapData])

  const mapTransform = useMemo(() => {
    const translateX = isLocated ? '-8%' : '0%'
    const translateY = isLocated ? '4%' : '0%'

    return `translate(${translateX}, ${translateY}) scale(${zoomLevel})`
  }, [isLocated, zoomLevel])

  function handleZoomIn() {
    setIsLocated(false)
    setZoomLevel((currentZoom) => Math.min(1.65, Number((currentZoom + 0.15).toFixed(2))))
  }

  function handleZoomOut() {
    setIsLocated(false)
    setZoomLevel((currentZoom) => Math.max(0.9, Number((currentZoom - 0.15).toFixed(2))))
  }

  function handleLocate() {
    setIsLocated((currentState) => {
      const nextState = !currentState
      if (nextState) {
        setZoomLevel((currentZoom) => Math.max(currentZoom, 1.15))
      }
      return nextState
    })
  }

  return (
    <article className="map-card">
      <div className="section-head">
        <div>
          <h3>{mapData?.title ?? 'Map overview'}</h3>
        </div>
      </div>

      <div className="map-panel" aria-label="Product style route map">
        <div className="map-controls" aria-label="Map controls">
          <button
            className="map-control-btn"
            type="button"
            aria-label="Zoom in"
            title="Zoom in"
            onClick={handleZoomIn}
          >
            <ZoomInIcon />
          </button>
          <button
            className="map-control-btn"
            type="button"
            aria-label="Zoom out"
            title="Zoom out"
            onClick={handleZoomOut}
          >
            <ZoomOutIcon />
          </button>
          <button
            className={isLocated ? 'map-control-btn is-active' : 'map-control-btn'}
            type="button"
            aria-label="Locate current position"
            title="Locate current position"
            aria-pressed={isLocated}
            onClick={handleLocate}
          >
            <LocateIcon />
          </button>
        </div>

        <div className="map-scene" style={{ transform: mapTransform }}>
          <div className="map-grid" />
          <div className="road one" />
          <div className="road two" />
          <div className="road three" />
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
                <g key={`${point.type}-${point.seq}`}>
                  <circle
                    cx={point.x}
                    cy={point.y}
                    r="3.2"
                    fill="#ffbf47"
                    stroke="#0c1c2d"
                    strokeWidth="1.2"
                  />
                  <text
                    x={point.x}
                    y={point.y + 1}
                    textAnchor="middle"
                    fontSize="3.2"
                    fontWeight="700"
                    fill="#0c1c2d"
                  >
                    {point.seq}
                  </text>
                </g>
              ))}
              {geometry.path[0] ? (
                <circle
                  cx={geometry.path[0].x}
                  cy={geometry.path[0].y}
                  r="4.6"
                  fill={isLocated ? '#ffbf47' : '#0c1c2d'}
                />
              ) : null}
              {geometry.path.at(-1) ? (
                <circle cx={geometry.path.at(-1).x} cy={geometry.path.at(-1).y} r="4.8" fill="#14507a" />
              ) : null}
            </svg>
          ) : (
            <>
              <div className="route-shape" />
              <div className={isLocated ? 'marker start is-located' : 'marker start'}>S</div>
              <div className="marker poi-1">1</div>
              <div className="marker poi-2">2</div>
              <div className="marker end">V</div>
            </>
          )}
          <div className={isLocated ? 'user-pulse is-visible' : 'user-pulse'} />

          {callouts.map((callout) => (
            <div
              key={callout.key}
              className={`map-callout ${callout.key}`}
              style={callout.position ? { left: `${callout.position.x}%`, top: `${callout.position.y}%` } : undefined}
            >
              {callout.label}
            </div>
          ))}
        </div>

        <div className="map-zoom-indicator" aria-live="polite">
          <span>Map zoom</span>
          <strong>{Math.round(zoomLevel * 100)}%</strong>
        </div>
      </div>

      {summaryCards.length > 0 ? (
        <div className="map-summary">
          {summaryCards.map((card) => (
            <div key={card.label} className="summary-card">
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </div>
          ))}
        </div>
      ) : null}

      <div className="map-facilities">
        <div className="map-facilities-head">
          <h4>{sectionTitle}</h4>
          {sectionBody ? <p>{sectionBody}</p> : null}
        </div>

        {facilityItems.length > 0 ? (
          <div className="route-list">
            {facilityItems.map((item, index) => (
              <DirectionsFacilityItem
                key={item.id}
                item={item}
                stepNumber={index + 1}
                isLast={index === facilityItems.length - 1}
              />
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}
