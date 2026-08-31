import { useState } from 'react'
import { ChevronDownIcon } from './Icons'

function findMatches(options, typedText) {
  if (typedText.trim().length < 3) {
    return []
  }

  return options.filter((item) =>
    item.toLowerCase().includes(typedText.trim().toLowerCase()),
  )
}

export default function CollapsibleSearchPanel({ data }) {
  const [isOpen, setIsOpen] = useState(false)
  const [sport, setSport] = useState(data.sport)
  const [suburb, setSuburb] = useState(data.suburbOrPostcode)
  const [selectedAmenities, setSelectedAmenities] = useState(
    data.defaultSelectedAmenities ?? data.amenityOptions ?? [],
  )
  const [activeDistance, setActiveDistance] = useState(data.activeDistance)
  const [showSports, setShowSports] = useState(false)
  const [showSuburbs, setShowSuburbs] = useState(false)
  const [formError, setFormError] = useState('')
  const [previewStartPoint, setPreviewStartPoint] = useState(data.startPoint)

  const sportMatches = findMatches(data.sportOptions ?? [], sport)
  const suburbMatches = findMatches(data.suburbOptions ?? [], suburb)

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
    setShowSports(false)
    setShowSuburbs(false)
    setFormError('')
    setPreviewStartPoint(data.startPoint)
  }

  function handleSearch(event) {
    event.preventDefault()

    if (sport.trim() === '' && suburb.trim() === '') {
      setFormError('Choose a sport and a suburb or postcode.')
      return
    }

    if (sport.trim() === '') {
      setFormError('Choose a sport.')
      return
    }

    if (suburb.trim() === '') {
      setFormError('Choose a suburb or postcode.')
      return
    }

    setFormError('')
    setShowSports(false)
    setShowSuburbs(false)
    setPreviewStartPoint(`${suburb.trim()} accessible drop-off`)
    setIsOpen(false)
  }

  return (
    <details className="drawer-card" open={isOpen}>
      <summary
        className="drawer-summary"
        onClick={(event) => {
          event.preventDefault()
          setIsOpen((currentValue) => !currentValue)
        }}
      >
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
            <strong>{previewStartPoint}</strong>
          </div>
          <div className="location-line">
            <span>Destination</span>
            <strong>{data.destination}</strong>
          </div>
        </div>
      </summary>

      <div className="drawer-content">
        <form className="drawer-content-inner" onSubmit={handleSearch}>
          <div className="field-stack panel-field">
            <label className="field-label panel-label" htmlFor="panel-sport">
              Sport <span className="required">*</span>
            </label>
            <div className="panel-input-wrap">
              <input
                id="panel-sport"
                type="text"
                className="search-input panel-input"
                placeholder="eg: Basketball"
                autoComplete="off"
                value={sport}
                onFocus={() => setShowSports(true)}
                onBlur={() => {
                  window.setTimeout(() => setShowSports(false), 120)
                }}
                onChange={(event) => {
                  setSport(event.target.value)
                  setShowSports(true)
                }}
              />

              {showSports && sportMatches.length > 0 ? (
                <ul className="suggestions">
                  {sportMatches.map((item) => (
                    <li key={item}>
                      <button
                        type="button"
                        onMouseDown={() => {
                          setSport(item)
                          setShowSports(false)
                        }}
                      >
                        {item}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}

              {showSports && sport.trim().length >= 3 && sportMatches.length === 0 ? (
                <p className="no-match">No sport found with that name.</p>
              ) : null}
            </div>
          </div>

          <div className="field-stack panel-field">
            <label className="field-label panel-label" htmlFor="panel-suburb">
              Suburb or postcode <span className="required">*</span>
            </label>
            <div className="panel-input-wrap">
              <input
                id="panel-suburb"
                type="text"
                className="search-input panel-input"
                placeholder="eg: North Melbourne or 3051"
                autoComplete="off"
                value={suburb}
                onFocus={() => setShowSuburbs(true)}
                onBlur={() => {
                  window.setTimeout(() => setShowSuburbs(false), 120)
                }}
                onChange={(event) => {
                  setSuburb(event.target.value)
                  setShowSuburbs(true)
                }}
              />

              {showSuburbs && suburbMatches.length > 0 ? (
                <ul className="suggestions">
                  {suburbMatches.map((item) => (
                    <li key={item}>
                      <button
                        type="button"
                        onMouseDown={() => {
                          setSuburb(item)
                          setShowSuburbs(false)
                        }}
                      >
                        {item}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}

              {showSuburbs && suburb.trim().length >= 3 && suburbMatches.length === 0 ? (
                <p className="no-match">Try a Greater Melbourne suburb or postcode.</p>
              ) : null}
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
            <div className="distance-options" aria-label="Corridor distance selector">
              {data.distanceOptions.map((option) => (
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
                    name="facility-distance"
                    value={option}
                    checked={option === activeDistance}
                    onChange={(event) => setActiveDistance(event.target.value)}
                  />
                  {option}
                </label>
              ))}
            </div>
          </div>

          {formError ? (
            <p className="form-error" role="alert">
              {formError}
            </p>
          ) : null}

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
    </details>
  )
}
