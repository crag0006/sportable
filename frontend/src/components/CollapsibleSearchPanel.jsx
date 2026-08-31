import { useState } from 'react'
import { ChevronDownIcon } from './Icons'

export default function CollapsibleSearchPanel({ data }) {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <details
      className="drawer-card"
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary className="drawer-summary">
        <div className="drawer-head">
          <div>
            <p className="drawer-title">{data.title}</p>
            <p className="drawer-subtitle">{data.subtitle}</p>
          </div>
          <span className="drawer-chevron">
            <ChevronDownIcon />
          </span>
        </div>

        <div className="location-pills" aria-label="Collapsed route setup preview">
          <div className="location-line">
            <span>Start point</span>
            <strong>{data.startPoint}</strong>
          </div>
          <div className="location-line">
            <span>Destination</span>
            <strong>{data.destination}</strong>
          </div>
        </div>
      </summary>

      <div className="drawer-content">
        <div className="drawer-content-inner">
          <div className="field-stack">
            <span className="field-label">Sport *</span>
            <div className="search-input">{data.sport}</div>
          </div>

          <div className="field-stack">
            <span className="field-label">Suburb or postcode *</span>
            <div className="search-input">{data.suburbOrPostcode}</div>
          </div>

          <div className="field-stack">
            <span className="field-label">Amenities</span>
            <div className="amenity-checks">
              {data.amenities.map((item) => (
                <div key={item} className="amenity-item">
                  ✓ {item}
                </div>
              ))}
            </div>
          </div>

          <div className="field-stack">
            <span className="field-label">Distance to a facility</span>
            <div className="selector" aria-label="Corridor distance selector">
              {data.distanceOptions.map((option) => (
                <span
                  key={option}
                  className={option === data.activeDistance ? 'active' : undefined}
                >
                  {option}
                </span>
              ))}
            </div>
          </div>

          <div className="drawer-actions">
            <button className="drawer-btn ghost" type="button">
              Clear
            </button>
            <button className="drawer-btn solid" type="button">
              Search venues
            </button>
          </div>
        </div>
      </div>
    </details>
  )
}
