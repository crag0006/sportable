import { useState } from 'react'
import HomepageVenueCard from '../components/HomepageVenueCard'
import { FACILITY_INFO, PLACE_NAMES, SPORTS, SUBURBS, VENUES } from '../data/homepageVenues'

function findMatches(list, typedText) {
  if (typedText.length < 3) {
    return []
  }

  return list.filter((item) => item.toLowerCase().includes(typedText.toLowerCase()))
}

export default function HomePage() {
  const [sport, setSport] = useState('Basketball')
  const [suburb, setSuburb] = useState('Preston 3072')
  const [toilet, setToilet] = useState(true)
  const [parking, setParking] = useState(false)
  const [stop, setStop] = useState(true)
  const [change, setChange] = useState(false)
  const [limit, setLimit] = useState('1000')
  const [showSports, setShowSports] = useState(false)
  const [showSuburbs, setShowSuburbs] = useState(false)
  const [results, setResults] = useState(null)
  const [formError, setFormError] = useState('')

  function getAmenityState(amenity) {
    if (!amenity || amenity.state === 'none') {
      return 'unknown'
    }

    if (amenity.state === 'absent') {
      return 'absent'
    }

    const facilityDistance = Number(amenity.distance)
    const selectedLimit = Number(limit)

    if (limit === '' || facilityDistance <= selectedLimit) {
      return 'within'
    }

    return 'beyond'
  }

  function runSearch(event) {
    if (event) {
      event.preventDefault()
    }

    if (sport === '' && suburb === '') {
      setFormError('Choose a sport and a suburb or postcode.')
      return
    }

    if (sport === '') {
      setFormError('Choose a sport.')
      return
    }

    if (suburb === '') {
      setFormError('Choose a suburb or postcode.')
      return
    }

    setFormError('')
    setShowSports(false)
    setShowSuburbs(false)

    const postcode = suburb.slice(-4)
    const sportVenues = VENUES.filter((venue) => venue.sports.includes(sport))
    const selectedAmenities = []

    if (toilet) selectedAmenities.push('toilet')
    if (parking) selectedAmenities.push('parking')
    if (stop) selectedAmenities.push('stop')
    if (change) selectedAmenities.push('change')

    const matchedVenues = []
    const missingInfoVenues = []

    sportVenues.forEach((venue) => {
      let allMatch = true
      let hasMissingInfo = false

      selectedAmenities.forEach((key) => {
        const amenity = venue.amenities[key]
        const state = getAmenityState(amenity)

        if (state !== 'within') {
          allMatch = false
        }

        if (state === 'unknown') {
          hasMissingInfo = true
        }
      })

      if (allMatch) {
        matchedVenues.push(venue)
      } else if (hasMissingInfo) {
        missingInfoVenues.push(venue)
      }
    })

    matchedVenues.sort((firstVenue, secondVenue) => firstVenue.distance - secondVenue.distance)

    setResults({
      total: sportVenues.length,
      matched: matchedVenues,
      undocumented: missingInfoVenues,
      place: PLACE_NAMES[postcode] || suburb,
      searchedSport: sport,
      searchedLimit: limit,
      selectedAmenities,
    })
  }

  function handleClear() {
    setSport('')
    setSuburb('')
    setToilet(false)
    setParking(false)
    setStop(false)
    setChange(false)
    setLimit('')
    setFormError('')
    setShowSports(false)
    setShowSuburbs(false)
  }

  const sportMatches = findMatches(SPORTS, sport)
  const suburbMatches = findMatches(SUBURBS, suburb)

  return (
    <div className="home-split">
      <div className="home-split-left">
        <div className="home-hero-brand">
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="4" r="2" />
            <path d="M11 8v6h5l3 6" />
            <path d="M15.5 14a5.5 5.5 0 1 1-6-5.48" />
          </svg>

          <div>
            <div className="home-hero-name">SportAble</div>
            <div className="home-hero-tagline">Know more. Play more.</div>
          </div>
        </div>

        <h1 className="home-hero-headline">No limits. Just possibilities.</h1>

        <form className="home-panel" onSubmit={runSearch}>
          <div className="home-field">
            <label htmlFor="home-sport">
              Sport <span className="home-required">*</span>
            </label>
            <input
              id="home-sport"
              type="text"
              className="home-input"
              placeholder="eg: Basketball"
              autoComplete="off"
              value={sport}
              onFocus={() => setShowSports(true)}
              onBlur={() => window.setTimeout(() => setShowSports(false), 120)}
              onChange={(event) => {
                setSport(event.target.value)
                setShowSports(true)
              }}
            />

            {showSports && sportMatches.length > 0 ? (
              <ul className="home-suggestions">
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

            {showSports && sport.length >= 3 && sportMatches.length === 0 ? (
              <p className="home-no-match">No sport found with that name.</p>
            ) : null}
          </div>

          <div className="home-field home-second-field">
            <label htmlFor="home-suburb">
              Suburb or postcode <span className="home-required">*</span>
            </label>
            <input
              id="home-suburb"
              type="text"
              className="home-input"
              placeholder="eg: Melbourne CBD or 3000"
              autoComplete="off"
              value={suburb}
              onFocus={() => setShowSuburbs(true)}
              onBlur={() => window.setTimeout(() => setShowSuburbs(false), 120)}
              onChange={(event) => {
                setSuburb(event.target.value)
                setShowSuburbs(true)
              }}
            />

            {showSuburbs && suburbMatches.length > 0 ? (
              <ul className="home-suggestions">
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

            {showSuburbs && suburb.length >= 3 && suburbMatches.length === 0 ? (
              <p className="home-no-match">Try a Greater Melbourne suburb or postcode.</p>
            ) : null}
          </div>

          <h2 className="home-section-title">Amenities</h2>

          <div className="home-checks">
            <label className="home-check">
              <input type="checkbox" checked={toilet} onChange={(event) => setToilet(event.target.checked)} />
              Accessible toilet
            </label>
            <label className="home-check">
              <input type="checkbox" checked={parking} onChange={(event) => setParking(event.target.checked)} />
              Accessible parking
            </label>
            <label className="home-check">
              <input type="checkbox" checked={stop} onChange={(event) => setStop(event.target.checked)} />
              Step-free transport stop
            </label>
            <label className="home-check">
              <input type="checkbox" checked={change} onChange={(event) => setChange(event.target.checked)} />
              Accessible change facility
            </label>
          </div>

          <h2 className="home-section-title">Distance to a facility</h2>

          <div className="home-distance-options">
            {[
              { value: '250', label: '250m' },
              { value: '500', label: '500m' },
              { value: '1000', label: '1km' },
            ].map((option) => (
              <label
                key={option.value}
                className={
                  limit === option.value
                    ? 'home-distance-option home-selected-distance'
                    : 'home-distance-option'
                }
              >
                <input
                  type="radio"
                  name="limit"
                  value={option.value}
                  checked={limit === option.value}
                  onChange={(event) => setLimit(event.target.value)}
                />
                {option.label}
              </label>
            ))}
          </div>

          {formError !== '' ? (
            <p className="home-form-error" role="alert">
              {formError}
            </p>
          ) : null}

          <div className="home-buttons">
            <button type="button" className="home-clear-button" onClick={handleClear}>
              Clear
            </button>
            <button type="submit" className="home-search-button">
              Search venues
            </button>
          </div>
        </form>
      </div>

      <div className="home-split-right" aria-live="polite">
        {results === null ? (
          <div className="home-photo" />
        ) : (
          <div className="home-results">
            <div className="home-results-heading">
              <div>
                <h2>
                  {results.matched.length} of {results.total} venues found
                </h2>
                <p>
                  {results.searchedSport} near {results.place}
                </p>
              </div>

              {results.searchedLimit !== '' ? (
                <span className="home-filter-badge">
                  {results.searchedLimit === '1000' ? '1 km' : `${results.searchedLimit} m`} facility
                  limit
                </span>
              ) : null}
            </div>

            {results.matched.length === 0 ? (
              <div className="home-empty-card">
                <h3>No matching venues</h3>
                <p>Try removing an amenity or choosing a bigger distance.</p>
              </div>
            ) : null}

            {results.matched.map((venue) => (
              <HomepageVenueCard key={venue.id} venue={venue} limit={results.searchedLimit} />
            ))}

            {results.matched.length > 0 ? (
              <div className="home-legend">
                <div className="home-legend-item">
                  <span className="home-legend-box home-available-box" />
                  Within selected distance
                </div>
                <div className="home-legend-item">
                  <span className="home-legend-box home-problem-box" />
                  Outside distance / unavailable
                </div>
                <div className="home-legend-item">
                  <span className="home-legend-box home-unknown-box" />
                  No published information
                </div>
              </div>
            ) : null}

            {results.undocumented.length > 0 ? (
              <div className="home-missing-section">
                <h3>Missing accessibility information</h3>
                {results.undocumented.map((venue) => {
                  const missingFacilities = results.selectedAmenities.filter((key) => {
                    const item = venue.amenities[key]
                    return !item || item.state === 'none'
                  })

                  return (
                    <div className="home-missing-venue" key={venue.id}>
                      <strong>{venue.name}</strong>
                      {missingFacilities.map((key) => (
                        <p key={key}>
                          {FACILITY_INFO[key].fullName} information is not available. Please
                          contact the venue to confirm before visiting.
                        </p>
                      ))}
                    </div>
                  )
                })}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
