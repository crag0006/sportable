import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

function parseDistanceValue(label) {
  if (!label) return ''

  const numericValue = Number.parseFloat(label)
  if (Number.isNaN(numericValue)) return ''

  if (label.toLowerCase().includes('km')) {
    return String(Math.round(numericValue * 1000))
  }

  return String(Math.round(numericValue))
}

export default function StaticSearchPanel({ data }) {
  const navigate = useNavigate()
  const [sport, setSport] = useState(data.sport)
  const [suburb, setSuburb] = useState(data.suburbOrPostcode)
  const [selectedAmenities, setSelectedAmenities] = useState(
    data.defaultSelectedAmenities ?? data.amenityOptions ?? [],
  )
  const [activeDistance, setActiveDistance] = useState(data.activeDistance)

  function toggleAmenity(amenity) {
    setSelectedAmenities((currentAmenities) =>
      currentAmenities.includes(amenity)
        ? currentAmenities.filter((item) => item !== amenity)
        : [...currentAmenities, amenity],
    )
  }

  function handleClear() {
    setSport(data.sport)
    setSuburb(data.suburbOrPostcode)
    setSelectedAmenities(data.defaultSelectedAmenities ?? data.amenityOptions ?? [])
    setActiveDistance(data.activeDistance)
  }

  function handleSearch(event) {
    event.preventDefault()

    navigate('/', {
      state: {
        draftSearch: {
          sport: sport.trim(),
          suburb: suburb.trim(),
          limit: parseDistanceValue(activeDistance),
          selectedAmenities,
        },
        autoSearch: true,
      },
    })
  }

  return (
    <section className="drawer-card static-search-panel">
      <div className="drawer-summary static-search-panel-summary">
        <div className="drawer-head">
          <div>
            <p className="drawer-title">{data.title}</p>
            <p className="drawer-subtitle">{data.subtitle}</p>
          </div>
        </div>

        <div className="location-pills" aria-label="Route setup preview">
          <div className="location-line">
            <span>Start point</span>
            <strong>{data.startPoint}</strong>
          </div>
          <div className="location-line">
            <span>Destination</span>
            <strong>{data.destination}</strong>
          </div>
        </div>
      </div>

      <div className="drawer-content static-search-panel-content">
        <form className="drawer-content-inner" onSubmit={handleSearch}>
          <div className="field-stack panel-field">
            <label className="field-label panel-label" htmlFor="static-panel-sport">
              Sport <span className="required">*</span>
            </label>
            <div className="panel-input-wrap">
              <input
                id="static-panel-sport"
                type="text"
                className="search-input panel-input"
                placeholder="eg: Basketball"
                autoComplete="off"
                value={sport}
                onChange={(event) => setSport(event.target.value)}
              />
            </div>
          </div>

          <div className="field-stack panel-field">
            <label className="field-label panel-label" htmlFor="static-panel-suburb">
              Suburb or postcode <span className="required">*</span>
            </label>
            <div className="panel-input-wrap">
              <input
                id="static-panel-suburb"
                type="text"
                className="search-input panel-input"
                placeholder="eg: North Melbourne or 3051"
                autoComplete="off"
                value={suburb}
                onChange={(event) => setSuburb(event.target.value)}
              />
            </div>
          </div>

          <div className="field-stack">
            <span className="field-label">Amenities</span>
            <div className="amenity-checks amenity-checks--interactive">
              {(data.amenityOptions ?? []).map((item) => (
                <label key={item} className="amenity-item amenity-check">
                  <input
                    type="checkbox"
                    checked={selectedAmenities.includes(item)}
                    onChange={() => toggleAmenity(item)}
                  />
                  <span>{item}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="field-stack">
            <span className="field-label">Distance to a facility</span>
            <div className="distance-options" aria-label="Facility distance selector">
              {(data.distanceOptions ?? []).map((option) => (
                <label
                  key={option}
                  className={
                    option === activeDistance
                      ? 'distance-option selected-distance'
                      : 'distance-option'
                  }
                >
                  <input
                    type="radio"
                    name="static-facility-distance"
                    value={option}
                    checked={option === activeDistance}
                    onChange={(event) => setActiveDistance(event.target.value)}
                  />
                  {option}
                </label>
              ))}
            </div>
          </div>

          <div className="drawer-actions buttons">
            <button className="clear-button drawer-btn ghost" type="button" onClick={handleClear}>
              Clear
            </button>
            <button className="search-button drawer-btn solid" type="submit">
              Search venues
            </button>
          </div>
        </form>
      </div>
    </section>
  )
}
