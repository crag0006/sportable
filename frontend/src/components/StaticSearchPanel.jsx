import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDownIcon } from './Icons'

function findMatches(options, typedText) {
  if (typedText.trim().length < 1) {
    return []
  }

  return options.filter((item) => item.toLowerCase().includes(typedText.trim().toLowerCase()))
}

function parseDistanceValue(label) {
  if (!label) return ''

  const numericValue = Number.parseFloat(label)
  if (Number.isNaN(numericValue)) return ''

  if (label.toLowerCase().includes('km')) {
    return String(Math.round(numericValue * 1000))
  }

  return String(Math.round(numericValue))
}

function getCurrentLocation() {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new Error('Current location is not available in this browser.'))
      return
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        })
      },
      () => {
        reject(new Error('Location access was blocked. Choose a suburb or postcode instead.'))
      },
      {
        enableHighAccuracy: true,
        timeout: 8000,
      },
    )
  })
}

export default function StaticSearchPanel({ data }) {
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const [sport, setSport] = useState(data.sport)
  const [startPoint, setStartPoint] = useState(data.startPoint)
  const [selectedAmenities, setSelectedAmenities] = useState(
    data.defaultSelectedAmenities ?? data.amenityOptions ?? [],
  )
  const [activeDistance, setActiveDistance] = useState(data.activeDistance)
  const [showStartPoints, setShowStartPoints] = useState(false)
  const [formError, setFormError] = useState('')
  const [previewStartPoint, setPreviewStartPoint] = useState(data.startPoint)

  const startPointMatches = findMatches(data.startPointOptions ?? [], startPoint)

  useEffect(() => {
    setSport(data.sport)
    setStartPoint(data.startPoint)
    setSelectedAmenities(data.defaultSelectedAmenities ?? data.amenityOptions ?? [])
    setActiveDistance(data.activeDistance)
    setPreviewStartPoint(data.startPoint)
  }, [
    data.activeDistance,
    data.amenityOptions,
    data.defaultSelectedAmenities,
    data.sport,
    data.startPoint,
  ])

  function toggleAmenity(amenity) {
    setSelectedAmenities((currentAmenities) =>
      currentAmenities.includes(amenity)
        ? currentAmenities.filter((item) => item !== amenity)
        : [...currentAmenities, amenity],
    )
  }

  function handleClear() {
    setSport(data.sport)
    setStartPoint(data.startPoint)
    setSelectedAmenities(data.defaultSelectedAmenities ?? data.amenityOptions ?? [])
    setActiveDistance(data.activeDistance)
    setShowStartPoints(false)
    setFormError('')
    setPreviewStartPoint(data.startPoint)
  }

  async function handleSearch(event) {
    event.preventDefault()

    if (sport.trim() === '') {
      setFormError('Choose a sport.')
      return
    }

    if (startPoint.trim() === '') {
      setFormError('Choose current location or enter a suburb/postcode.')
      return
    }

    setFormError('')
    setShowStartPoints(false)

    try {
      let fromValue = startPoint.trim()
      let startLabel = startPoint.trim()

      if (startPoint.trim() === 'Current location (test)') {
        const currentLocation = await getCurrentLocation()
        fromValue = `${currentLocation.latitude.toFixed(6)},${currentLocation.longitude.toFixed(6)}`
        startLabel = 'Current location (test)'
      }

      setPreviewStartPoint(startLabel)
      setIsOpen(false)

      if (data.currentPath) {
        const query = new URLSearchParams()
        query.set('from', fromValue)
        query.set('startLabel', startLabel)

        const parsedDistance = parseDistanceValue(activeDistance)
        if (parsedDistance) {
          query.set('within', parsedDistance)
        }

        navigate(`${data.currentPath}?${query.toString()}`)
        return
      }

      navigate('/', {
        state: {
          draftSearch: {
            sport: sport.trim(),
            suburb: startLabel,
            limit: parseDistanceValue(activeDistance),
            selectedAmenities,
          },
          autoSearch: true,
        },
      })
    } catch (caughtError) {
      setFormError(caughtError.message)
    }
  }

  return (
    <details className="drawer-card static-search-panel" open={isOpen}>
      <summary
        className="drawer-summary static-search-panel-summary"
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

        <div className="location-pills" aria-label="Route setup preview">
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
            <label className="field-label panel-label" htmlFor="static-panel-start-point">
              Start point <span className="required">*</span>
            </label>
            <div className="panel-input-wrap">
              <input
                id="static-panel-start-point"
                type="text"
                className="search-input panel-input"
                placeholder="Current location (test) or postcode"
                autoComplete="off"
                value={startPoint}
                onFocus={() => setShowStartPoints(true)}
                onBlur={() => {
                  window.setTimeout(() => setShowStartPoints(false), 120)
                }}
                onChange={(event) => {
                  setStartPoint(event.target.value)
                  setShowStartPoints(true)
                }}
              />

              {showStartPoints && startPointMatches.length > 0 ? (
                <ul className="suggestions">
                  {startPointMatches.map((item) => (
                    <li key={item}>
                      <button
                        type="button"
                        onMouseDown={() => {
                          setStartPoint(item)
                          setShowStartPoints(false)
                        }}
                      >
                        {item}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}

              {showStartPoints &&
              startPoint.trim().length >= 1 &&
              startPointMatches.length === 0 ? (
                <p className="no-match">Choose Current location (test) or enter a suburb/postcode.</p>
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
    </details>
  )
}
