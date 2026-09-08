import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getCorridor, getVenue } from '../api/venues'
import RouteMap from '../components/RouteMap'
import FacilityCard from '../components/FacilityCard'

const PAGE_SIZE = 6

const TYPE_ICON = {
  toilet: 'toilet',
  parking: 'parking',
  stop: 'transport',
}

const TYPE_LABEL_FALLBACK = {
  toilet: 'Accessible toilet',
  parking: 'Accessible parking',
  stop: 'Accessible transport stop',
}

// Some facilities from the backend have no name, just an address, or neither.
// This picks the best thing we have to show as the card title.
function formatFacilityTitle(facility) {
  if (facility.name) return facility.name
  if (facility.address) return facility.address
  return TYPE_LABEL_FALLBACK[facility.type] || 'Accessible facility'
}

function formatFacilityDescription(facility) {
  const parts = []

  if (facility.name && facility.address && facility.address !== facility.name) {
    parts.push(facility.address)
  }

  if (facility.type === 'toilet') {
    if (facility.opening_hours) parts.push(facility.opening_hours)
    if (facility.mlak) parts.push('MLAK key required')
  }

  if (facility.source?.name) {
    parts.push(`Source: ${facility.source.name}`)
  }

  return parts.length > 0 ? parts.join(' · ') : 'No further detail published for this facility.'
}

// Turns the raw corridor facilities into the shape FacilityCard already knows how to render,
// sorted so the closest ones show first.
function buildFacilityCards(facilities) {
  return [...facilities]
    .sort((a, b) => a.distance_from_path_m - b.distance_from_path_m)
    .map((facility) => ({
      id: `facility-${facility.seq}`,
      icon: TYPE_ICON[facility.type] || 'ramp',
      title: formatFacilityTitle(facility),
      description: formatFacilityDescription(facility),
      state: 'within', // the backend already filtered these to "within_m", so they're all confirmed close
      pillText: `${facility.distance_from_path_m} m from the corridor`,
      lat: facility.lat,
      lon: facility.lon,
      type: facility.type,
    }))
}

export default function DirectionsPage() {
  const { id } = useParams()
  const [venue, setVenue] = useState(null)
  const [corridor, setCorridor] = useState(null)
  // locationStatus: locating | granted | denied | unsupported
  const [locationStatus, setLocationStatus] = useState('locating')
  const [manualPlace, setManualPlace] = useState('')
  const [error, setError] = useState('')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  useEffect(() => {
    getVenue(id)
      .then(setVenue)
      .catch((err) => setError(err.message))
  }, [id])

  function fetchCorridorFrom(fromValue) {
    setError('')
    getCorridor(id, fromValue)
      .then((data) => {
        setCorridor(data)
        setLocationStatus('granted')
        setVisibleCount(PAGE_SIZE)
      })
      .catch((err) => {
        setError(err.message)
      })
  }

  // Ask the browser for the user's real location as soon as the page loads.
  useEffect(() => {
    if (!navigator.geolocation) {
      setLocationStatus('unsupported')
      return
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const from = `${position.coords.latitude},${position.coords.longitude}`
        fetchCorridorFrom(from)
      },
      () => {
        setLocationStatus('denied')
      },
      { timeout: 10000 },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  function handleManualSubmit(event) {
    event.preventDefault()
    if (!manualPlace.trim()) return
    fetchCorridorFrom(manualPlace.trim())
  }

  const facilityCards = useMemo(
    () => (corridor ? buildFacilityCards(corridor.facilities) : []),
    [corridor],
  )

  const visibleFacilities = facilityCards.slice(0, visibleCount)

  return (
    <div className="venue-page">
      <header className="venue-topbar">
        <div className="venue-topbar-inner">
          <div className="venue-brand">
            <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="4" r="2" />
              <path d="M11 8v6h5l3 6" />
              <path d="M15.5 14a5.5 5.5 0 1 1-6-5.48" />
            </svg>
            <div>
              <div className="venue-brand-name">SportAble</div>
              <div className="venue-brand-tagline">Know more. Play more.</div>
            </div>
          </div>
          <Link className="venue-back-link" to={`/venues/${id}`}>
            ‹ Back to venue details
          </Link>
        </div>
      </header>

      <main className="venue-content">
        <section className="hero-card">
          <p className="eyebrow">Getting there</p>
          <h2>{venue?.name || 'This venue'}</h2>
          <p>A straight-line corridor from your location to the venue, plus accessibility facilities recorded nearby.</p>
        </section>

        {locationStatus === 'locating' && (
          <section className="section-card">
            <p>Finding your location…</p>
          </section>
        )}

        {(locationStatus === 'denied' || locationStatus === 'unsupported') && !corridor && (
          <section className="section-card">
            <h3>We couldn't get your location</h3>
            <p>
              {locationStatus === 'unsupported'
                ? 'Your browser does not support location access.'
                : 'Location access was not granted.'}{' '}
              You can type a suburb or postcode instead.
            </p>
            <form onSubmit={handleManualSubmit} className="manual-location-form">
              <input
                type="text"
                value={manualPlace}
                onChange={(event) => setManualPlace(event.target.value)}
                placeholder="e.g. Melbourne 3000"
                aria-label="Suburb or postcode"
              />
              <button type="submit">Use this instead</button>
            </form>
          </section>
        )}

        {error && (
          <section className="section-card">
            <p>{error}</p>
          </section>
        )}

        {corridor && (
          <>
            <section className="section-card">
              <div className="section-head">
                <div><h3>What's nearby</h3></div>
              </div>
              <div className="types-summary">
                {corridor.types.map((t) => (
                  <div key={t.type} className={`type-summary-card type-summary-card--${t.status}`}>
                    <span>{t.label}</span>
                    <strong>{t.status === 'found' ? t.count : 'No data'}</strong>
                  </div>
                ))}
              </div>
            </section>

            <section className="section-card">
              <div className="section-head">
                <div><h3>Corridor map</h3></div>
              </div>
              <p className="map-note">
                This is a straight-line corridor, not a walking route — no dataset confirms the path between these points is step-free.
              </p>
              <RouteMap corridor={corridor} facilities={facilityCards} />
            </section>

            <section className="section-card">
              <div className="section-head">
                <div><h3>Nearby accessibility facilities</h3></div>
              </div>
              <div className="facility-list">
                {visibleFacilities.map((facility) => (
                  <FacilityCard key={facility.id} facility={facility} />
                ))}
              </div>
              {visibleCount < facilityCards.length && (
                <button
                  className="view-more-button"
                  type="button"
                  onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
                >
                  View more facilities
                </button>
              )}
            </section>

            <section className="disclaimer-card">
              <h3>What this does and doesn't check</h3>
              {corridor.checked.map((line, index) => (
                <p key={`checked-${index}`}>✓ {line}</p>
              ))}
              {corridor.not_checked.map((line, index) => (
                <p key={`not-checked-${index}`}>✗ {line}</p>
              ))}
            </section>
          </>
        )}
      </main>
    </div>
  )
}