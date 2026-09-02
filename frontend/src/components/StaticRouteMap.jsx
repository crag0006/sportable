import { useMemo, useState } from 'react'
import DirectionsFacilityItem from './DirectionsFacilityItem'
import { LocateIcon, ZoomInIcon, ZoomOutIcon } from './Icons'

export default function StaticRouteMap({ mapData, facilities, sectionTitle, sectionBody }) {
  const [zoomLevel, setZoomLevel] = useState(1)
  const [isLocated, setIsLocated] = useState(false)
  const summaryCards = mapData?.summaryCards ?? []
  const callouts = mapData?.callouts ?? []
  const facilityItems = facilities ?? []

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
          <div className="route-shape" />
          <div className={isLocated ? 'marker start is-located' : 'marker start'}>S</div>
          <div className="marker poi-1">1</div>
          <div className="marker poi-2">2</div>
          <div className="marker end">V</div>
          <div className={isLocated ? 'user-pulse is-visible' : 'user-pulse'} />

          {callouts.map((callout) => (
            <div key={callout.key} className={`map-callout ${callout.key}`}>
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
            {facilityItems.map((item) => (
              <DirectionsFacilityItem key={item.id} item={item} />
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}
