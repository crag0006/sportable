import DirectionsFacilityItem from './DirectionsFacilityItem'
import { LocateIcon, ZoomInIcon, ZoomOutIcon } from './Icons'

const controlButtons = [
  { label: 'Zoom in', icon: <ZoomInIcon /> },
  { label: 'Zoom out', icon: <ZoomOutIcon /> },
  { label: 'Locate current position', icon: <LocateIcon /> },
]

export default function StaticRouteMap({ mapData, facilities, sectionTitle, sectionBody }) {
  return (
    <article className="map-card">
      <div className="section-head">
        <div>
          <h3>{mapData.title}</h3>
        </div>
      </div>

      <div className="map-panel" aria-label="Product style route map">
        <div className="map-grid" />

        <div className="map-controls" aria-label="Map controls">
          {controlButtons.map((control) => (
            <button
              key={control.label}
              className="map-control-btn"
              type="button"
              aria-label={control.label}
              title={control.label}
            >
              {control.icon}
            </button>
          ))}
        </div>

        <div className="road one" />
        <div className="road two" />
        <div className="road three" />
        <div className="route-shape" />
        <div className="marker start">S</div>
        <div className="marker poi-1">1</div>
        <div className="marker poi-2">2</div>
        <div className="marker end">V</div>

        {mapData.callouts.map((callout) => (
          <div
            key={callout.key}
            className={`map-callout ${callout.key}`}
          >
            {callout.label}
          </div>
        ))}
      </div>

      <div className="map-summary">
        {mapData.summaryCards.map((card) => (
          <div key={card.label} className="summary-card">
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </div>
        ))}
      </div>

      <div className="map-facilities">
        <div className="map-facilities-head">
          <h4>{sectionTitle}</h4>
          {sectionBody ? <p>{sectionBody}</p> : null}
        </div>

        <div className="route-list">
          {facilities.map((item) => (
            <DirectionsFacilityItem key={item.id} item={item} />
          ))}
        </div>
      </div>
    </article>
  )
}
