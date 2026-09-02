import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getConfig, getSports, getSuburbs, getVenue } from '../api/venues'
import AppShell from '../components/AppShell'
import FacilityCard from '../components/FacilityCard'
import MiniMapLinkCard from '../components/MiniMapLinkCard'
import StaticSearchPanel from '../components/StaticSearchPanel'
import VenueHero from '../components/VenueHero'
import { FACILITY_INFO, VENUES as HOME_VENUES } from '../data/homepageVenues'
import {
  searchPanelData,
  venueFacilities,
  venueDetailData,
} from '../data/venueData'

const AMENITY_CONFIG = {
  toilet: { icon: 'toilet' },
  parking: { icon: 'parking' },
  stop: { icon: 'transport' },
  change: { icon: 'change' },
}

const FACILITY_CONTENT_FALLBACK = Object.fromEntries(
  venueFacilities.map((item) => [item.id, item]),
)

function formatBandLabel(value) {
  return value === 1000 ? '1 km' : `${value} m`
}

function formatAddress(venue) {
  return venue.address || [venue.suburb, venue.postcode].filter(Boolean).join(' ') || 'Address not published'
}

function formatLocation(location) {
  if (location === 'at_venue') return 'At the venue'
  if (location === 'public_nearby') return 'Public nearby'
  if (location === 'unrecorded') return 'Unrecorded'
  return ''
}

function getAmenityLocationLabel(location, amenity) {
  if (location === 'at_venue') return 'At the venue'
  if (location === 'public_nearby') {
    return amenity?.name
      ? `Public facility near the venue (${amenity.name})`
      : 'Public facility near the venue'
  }
  if (location === 'unrecorded') return 'Location not published'
  return 'Location not published'
}

function getFacilityFallback(key) {
  return FACILITY_CONTENT_FALLBACK[key] ?? null
}

function getAmenityState(item, limit) {
  if (!item || item.state === 'none') {
    return 'unknown'
  }

  if (item.state === 'absent') {
    return 'absent'
  }

  if (item.state === 'confirmed') {
    return 'at_venue'
  }

  const facilityDistance = Number(item.distance)
  const selectedLimit = Number(limit)

  if (limit === '' || Number.isNaN(selectedLimit) || facilityDistance <= selectedLimit) {
    return 'within'
  }

  return 'beyond'
}

function getAmenitySummaryText(item, state) {
  if (state === 'at_venue') {
    return 'At the venue'
  }

  if (state === 'within') {
    return `${item.distance} m away`
  }

  if (state === 'beyond') {
    return `${item.distance} m away — beyond your limit`
  }

  if (state === 'absent') {
    return 'Not available'
  }

  return 'No published information — check with the venue'
}

function buildBadge(amenities) {
  if (amenities?.toilet?.state === 'confirmed') {
    return 'Accessible toilet on site'
  }

  if (Object.values(amenities ?? {}).some((item) => item?.state === 'recorded')) {
    return 'Nearby facilities recorded'
  }

  return 'Published information only'
}

function buildSummary(venue) {
  const amenities = venue.amenities ?? {}
  const sentences = []

  if (amenities.toilet?.state === 'confirmed') sentences.push('Accessible toilet at the venue.')
  if (amenities.parking?.state === 'confirmed') sentences.push('Accessible parking at the venue.')
  if (amenities.change?.state === 'recorded' && amenities.change.distance) {
    sentences.push(`Nearest change facility ${amenities.change.distance} m away.`)
  }
  if ((venue.unpublished ?? []).some((item) => item.key === 'enter')) {
    sentences.push('Step-free entry is not published.')
  }

  const panels = []

  if (sentences.length > 0) {
    panels.push({
      label: 'Venue summary',
      body: sentences.join(' '),
    })
  }

  const nearestRecorded = Object.values(amenities)
    .filter((item) => item?.state === 'recorded' && item?.distance)
    .sort((firstItem, secondItem) => firstItem.distance - secondItem.distance)[0]

  if (nearestRecorded) {
    panels.push({
      label: 'Nearest recorded facility',
      emphasis: `${nearestRecorded.distance} m`,
      body: nearestRecorded.name || 'Published nearby facility',
    })
  }

  return panels
}

function buildDescription(amenity, defaultLimit = 500, fallbackFacility = null) {
  if (!amenity || amenity.state === 'none') {
    return (
      fallbackFacility?.description ??
      'No published information. This is not a no — nobody has published data for this venue.'
    )
  }

  if (amenity.state === 'confirmed' && amenity.source?.name) {
    return `Recorded at the venue by ${amenity.source.name}.`
  }

  if (amenity.state === 'confirmed') {
    return fallbackFacility?.description ?? 'Recorded at the venue.'
  }

  if (amenity.state === 'recorded' && amenity.location === 'public_nearby') {
    if (amenity.distance > defaultLimit) {
      return `Nearest published facility is ${amenity.distance} m away — beyond your ${defaultLimit} m limit.`
    }

    return `Nearest published facility is ${amenity.distance} m away${amenity.name ? `, at ${amenity.name}` : ''}.`
  }

  if (amenity.state === 'recorded' && amenity.distance) {
    if (amenity.distance > defaultLimit) {
      return `Nearest published facility is ${amenity.distance} m away — beyond your ${defaultLimit} m limit.`
    }

    return `Nearest published facility is ${amenity.distance} m away.`
  }

  if (amenity.state === 'absent') {
    return `The venue's own record says this is not available.`
  }

  return ''
}

function getAmenityDetailValue(amenity, fallbackFacility = null) {
  if (amenity?.opening_hours) {
    return amenity.opening_hours
  }

  if (typeof amenity?.mlak === 'boolean') {
    return amenity.mlak ? 'Required' : 'Not required'
  }

  if (amenity?.name && amenity.location === 'public_nearby') {
    return amenity.name
  }

  return fallbackFacility?.thirdValue || '—'
}

function getAmenitySourceValue(amenity, fallbackFacility = null) {
  return amenity?.source?.name || fallbackFacility?.source || '—'
}

function getAmenityLocationValue(amenity, fallbackFacility = null) {
  if (amenity?.location) {
    return getAmenityLocationLabel(amenity.location, amenity)
  }

  return fallbackFacility?.location || 'Location not published'
}

function buildFacilityCards(venue, defaultLimit = 500) {
  const cards = []
  const amenities = venue.amenities ?? {}
  const limitValue = String(defaultLimit)

  Object.entries(AMENITY_CONFIG).forEach(([key, config]) => {
    const amenity = amenities[key]
    const homeInfo = FACILITY_INFO[key]
    const state = getAmenityState(amenity, limitValue)
    const fallbackFacility = getFacilityFallback(key)

    cards.push({
      id: key,
      title: homeInfo?.fullName ?? homeInfo?.name ?? key,
      description: buildDescription(amenity, defaultLimit, fallbackFacility),
      pillText: getAmenitySummaryText(amenity, state),
      source: amenity?.source?.name,
      updated: amenity?.source?.published_at ?? amenity?.source?.retrieved_at,
      location: amenity?.location ? formatLocation(amenity.location) : '',
      icon: config.icon,
      metaItems: [
        { label: 'Home status', value: getAmenitySummaryText(amenity, state) },
        { label: 'Source', value: getAmenitySourceValue(amenity, fallbackFacility) },
        { label: 'Detail', value: getAmenityDetailValue(amenity, fallbackFacility) },
        { label: 'Location', value: getAmenityLocationValue(amenity, fallbackFacility) },
      ],
    })
  })

  const entry = (venue.unpublished ?? []).find((item) => item.key === 'enter')

  if (entry) {
    cards.push({
      id: entry.key,
      title: entry.label,
      description: entry.reason,
      icon: 'ramp',
    })
  }

  return cards
}

function buildFallbackHero(venue) {
  return {
    eyebrow: 'Venue detail',
    title: venue.name,
    address: formatAddress(venue),
    badge: venue.distance ? `${venue.distance} km from current search` : '',
    tags: [...(venue.sports ?? []), venue.surface].filter(Boolean),
    panels: venueDetailData.hero.panels,
  }
}

export default function VenueDetailPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const [venue, setVenue] = useState(null)
  const [config, setConfig] = useState(null)
  const [sports, setSports] = useState([])
  const [suburbs, setSuburbs] = useState([])
  const [error, setError] = useState('')
  const fromQuery = (searchParams.get('from') || '').trim()
  const startLabelQuery = (searchParams.get('startLabel') || '').trim()
  const withinQuery = (searchParams.get('within') || '').trim()
  const fallbackVenue = useMemo(
    () => HOME_VENUES.find((item) => String(item.id) === String(id)) ?? null,
    [id],
  )
  const displayVenue = venue ?? fallbackVenue
  const sharedQuery = useMemo(() => {
    const query = new URLSearchParams()
    if (fromQuery) query.set('from', fromQuery)
    if (startLabelQuery) query.set('startLabel', startLabelQuery)
    if (withinQuery) query.set('within', withinQuery)
    const queryString = query.toString()
    return queryString ? `?${queryString}` : ''
  }, [fromQuery, startLabelQuery, withinQuery])

  const displayStartLabel = startLabelQuery || fromQuery || searchPanelData.startPoint

  useEffect(() => {
    let isMounted = true

    Promise.all([getVenue(id, { from: fromQuery || undefined }), getConfig(), getSports(), getSuburbs()])
      .then(([venueBody, configBody, sportsBody, suburbsBody]) => {
        if (!isMounted) return
        setVenue(venueBody)
        setConfig(configBody)
        setSports(sportsBody)
        setSuburbs(suburbsBody)
        setError('')
      })
      .catch((caughtError) => {
        if (!isMounted) return
        setError(caughtError.message)
      })

    return () => {
      isMounted = false
    }
  }, [fromQuery, id])

  const sidebarData = useMemo(() => {
    const defaultDistance = config?.default_distance_m

    return {
      ...searchPanelData,
      sport: displayVenue?.sports?.[0] ?? searchPanelData.sport,
      suburbOrPostcode:
        displayVenue?.suburb && displayVenue?.postcode
          ? `${displayVenue.suburb} ${displayVenue.postcode}`
          : searchPanelData.suburbOrPostcode,
      sportOptions: sports.length > 0 ? sports : searchPanelData.sportOptions,
      suburbOptions: suburbs.length > 0 ? suburbs : searchPanelData.suburbOptions,
      distanceOptions:
        config?.distance_bands_m?.map((value) => formatBandLabel(value)) ?? searchPanelData.distanceOptions,
      activeDistance: defaultDistance ? formatBandLabel(defaultDistance) : searchPanelData.activeDistance,
      destination: displayVenue?.name ?? searchPanelData.destination,
      startPoint: displayStartLabel,
      startPointOptions: ['Current location (test)', ...(suburbs.length > 0 ? suburbs : searchPanelData.suburbOptions)],
      currentPath: `/venues/${id}`,
    }
  }, [config, displayStartLabel, displayVenue, id, sports, suburbs])

  const heroData = useMemo(() => {
    if (!venue) {
      if (fallbackVenue) {
        return buildFallbackHero(fallbackVenue)
      }

      return venueDetailData.hero
    }

    return {
      eyebrow: 'Venue detail',
      title: venue.name,
      address: formatAddress(venue),
      badge: `Data retrieved ${venue.last_updated}`,
      tags: [...(venue.sports ?? []), venue.surface, venue.lga].filter(Boolean),
      panels: buildSummary(venue),
    }
  }, [fallbackVenue, venue])

  const facilities = useMemo(
    () => (displayVenue ? buildFacilityCards(displayVenue, config?.default_distance_m ?? 500) : []),
    [config, displayVenue],
  )

  const miniMapData = useMemo(() => {
    if (!venue?.lat || !venue?.lon || !venue?.reference_point) {
      return null
    }

    return {
      coordinates: [
        [venue.reference_point.latitude, venue.reference_point.longitude],
        [venue.lat, venue.lon],
      ],
      facilityPoints: Object.values(venue.amenities ?? {})
        .filter((item) => item?.lat && item?.lon)
        .slice(0, 3)
        .map((item, index) => ({
          seq: index + 1,
          type: item.location === 'public_nearby' ? 'toilet' : 'parking',
          lat: item.lat,
          lon: item.lon,
        })),
    }
  }, [venue])

  const mapPreviewCaption = useMemo(() => {
    if (venue?.reference_point?.label && venue?.distance) {
      return `${venue.distance} km from ${venue.reference_point.label}. Open the directions page for the full corridor view.`
    }

    return venueDetailData.mapPreview.caption
  }, [venue])

  return (
    <AppShell
      backTo={venueDetailData.backTo}
      backLabel={venueDetailData.backLabel}
      headline={venueDetailData.sidebarHeadline}
      sidebarChildren={
        <>
          <StaticSearchPanel data={sidebarData} />
          <MiniMapLinkCard
            label={venueDetailData.mapPreview.label}
            caption={mapPreviewCaption}
            linkLabel={venueDetailData.mapPreview.linkLabel}
            to={`/venues/${id}/directions${sharedQuery}`}
            mapData={miniMapData}
          />
        </>
      }
    >
      <VenueHero hero={heroData} />

      {error && !fallbackVenue ? (
        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>Venue information unavailable</h3>
            </div>
          </div>
          <p>{error}</p>
        </section>
      ) : null}

      {facilities.length > 0 ? (
        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>{venueDetailData.facilitiesSectionTitle}</h3>
            </div>
          </div>

          <div className="facility-list">
            {facilities.map((facility) => (
              <FacilityCard key={facility.id} facility={facility} />
            ))}
          </div>
        </section>
      ) : null}
    </AppShell>
  )
}
