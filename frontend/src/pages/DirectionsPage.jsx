import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getConfig, getSports, getSuburbs, getVenue } from '../api/venues'
import AppShell from '../components/AppShell'
import DirectionsHero from '../components/DirectionsHero'
import StaticSearchPanel from '../components/StaticSearchPanel'
import StaticRouteMap from '../components/StaticRouteMap'
import { VENUES as HOME_VENUES } from '../data/homepageVenues'
import {
  directionsFacilities,
  directionsPageData,
  searchPanelData,
} from '../data/venueData'

const ROUTE_ITEM_FALLBACK = Object.fromEntries(
  directionsFacilities.map((item) => [item.id, item]),
)

function formatBandLabel(value) {
  return value === 1000 ? '1 km' : `${value} m`
}

function formatAddress(venue) {
  return venue.address || [venue.suburb, venue.postcode].filter(Boolean).join(' ') || 'Address not published'
}

function getFallbackMetaValue(item, label) {
  return item?.meta?.find((metaItem) => metaItem.label === label)?.value || ''
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

function getAmenityRouteState(item, limit) {
  if (!item || item.state === 'none') return 'unknown'
  if (item.state === 'absent') return 'absent'
  if (item.state === 'confirmed') return 'at_venue'

  const distance = Number(item.distance)
  const selectedLimit = Number(limit)

  if (limit === '' || Number.isNaN(selectedLimit) || distance <= selectedLimit) {
    return 'within'
  }

  return 'beyond'
}

function getAmenityTag(type, item, state, fallbackItem) {
  if (type === 'toilet') {
    if (typeof item?.mlak === 'boolean') {
      return item.mlak ? 'Key required' : 'No key needed'
    }

    return fallbackItem?.tag || 'Toilet info'
  }

  if (type === 'parking') {
    if (state === 'at_venue' || state === 'within') return 'Confirmed'
    if (state === 'beyond') return 'Further away'
    if (state === 'absent') return 'Not available'
    return fallbackItem?.tag || 'Parking info'
  }

  if (type === 'stop') {
    if (state === 'at_venue' || state === 'within' || state === 'beyond') return 'Step-free'
    if (state === 'absent') return 'Not available'
    return fallbackItem?.tag || 'Transport info'
  }

  if (state === 'at_venue') return 'At the venue'
  if (state === 'within') return `${item.distance} m away`
  if (state === 'beyond') return `${item.distance} m away`
  if (state === 'absent') return 'Not available'
  return fallbackItem?.tag || 'No published info'
}

function getAmenityTagVariant(type, item, state, fallbackItem) {
  if (type === 'toilet' && typeof item?.mlak === 'boolean') {
    return item.mlak ? 'alert' : 'good'
  }

  if (type === 'stop' && (state === 'at_venue' || state === 'within' || state === 'beyond')) {
    return 'good'
  }

  if (state === 'at_venue' || state === 'within') return 'good'
  if (state === 'beyond') return 'alert'
  if (state === 'absent' || state === 'unknown') return fallbackItem?.tagVariant || 'alert'
  return fallbackItem?.tagVariant || 'good'
}

function buildAmenityRouteDescription(item, limit, fallbackItem) {
  if (!item || item.state === 'none') {
    return fallbackItem?.description || 'No published route-side information yet.'
  }

  if (item.state === 'absent') {
    return "The venue's own record says this is not available."
  }

  if (item.state === 'confirmed') {
    return item?.source?.name
      ? `Recorded at the venue by ${item.source.name}.`
      : 'Recorded at the venue.'
  }

  if (item.location === 'public_nearby' && item.distance) {
    if (Number(item.distance) > Number(limit)) {
      return `Nearest published facility is ${item.distance} m away${item.name ? `, at ${item.name}` : ''} — beyond your ${limit} m limit.`
    }

    return `Nearest published facility is ${item.distance} m away${item.name ? `, at ${item.name}` : ''}.`
  }

  if (item.distance) {
    return `Nearest published facility is ${item.distance} m away.`
  }

  return fallbackItem?.description || 'Published facility information is available.'
}

function buildAmenityRouteMeta(type, amenity, fallbackItem) {
  const rows = []

  rows.push({
    label: 'Distance',
    value: amenity?.distance ? `${amenity.distance} m` : getFallbackMetaValue(fallbackItem, 'Distance') || '—',
  })

  if (type === 'toilet') {
    rows.push({
      label: 'MLAK',
      value:
        typeof amenity?.mlak === 'boolean'
          ? amenity.mlak
            ? 'Key required'
            : 'Not required'
          : getFallbackMetaValue(fallbackItem, 'MLAK') || '—',
    })
  }

  if (type === 'parking') {
    rows.push({
      label: 'Hours',
      value: amenity?.opening_hours || getFallbackMetaValue(fallbackItem, 'Hours') || '—',
    })
  }

  if (type === 'stop') {
    rows.push({
      label: 'Access',
      value:
        amenity?.state === 'recorded' || amenity?.state === 'confirmed'
          ? 'Step-free'
          : getFallbackMetaValue(fallbackItem, 'Access') || '—',
    })
    rows.push({
      label: 'Stop type',
      value: getFallbackMetaValue(fallbackItem, 'Stop type') || '—',
    })
  }

  rows.push({
    label: 'Location',
    value: amenity?.location
      ? getAmenityLocationLabel(amenity.location, amenity)
      : getFallbackMetaValue(fallbackItem, 'Location') || 'Location not published',
  })

  return rows
}

function buildEntryRouteItem(unpublishedEntry, fallbackItem) {
  return {
    id: 'route-entry',
    title: unpublishedEntry?.label || fallbackItem?.title || 'Access entry',
    description: unpublishedEntry?.reason || fallbackItem?.description || 'Entry details are not published.',
    tag: fallbackItem?.tag || 'Not published',
    tagVariant: fallbackItem?.tagVariant || 'alert',
    icon: fallbackItem?.icon || 'ramp',
    meta: fallbackItem?.meta || [],
  }
}

function buildDirectionsFacilities(venue, defaultLimit) {
  const amenities = venue?.amenities ?? {}

  const amenityItems = [
    { key: 'toilet', routeId: 'route-toilet', title: 'Accessible toilets and facility', icon: 'toilet' },
    { key: 'parking', routeId: 'route-parking', title: 'Accessible parking', icon: 'parking' },
    { key: 'stop', routeId: 'route-stop', title: 'Step-free public transport stops', icon: 'transport' },
  ].map((config) => {
    const amenity = amenities[config.key]
    const fallbackItem = ROUTE_ITEM_FALLBACK[config.routeId]
    const state = getAmenityRouteState(amenity, defaultLimit)

    return {
      id: config.routeId,
      title: fallbackItem?.title || config.title,
      description: buildAmenityRouteDescription(amenity, defaultLimit, fallbackItem),
      tag: getAmenityTag(config.key, amenity, state, fallbackItem),
      tagVariant: getAmenityTagVariant(config.key, amenity, state, fallbackItem),
      icon: fallbackItem?.icon || config.icon,
      meta: buildAmenityRouteMeta(config.key, amenity, fallbackItem),
    }
  })

  const entry = (venue?.unpublished ?? []).find((item) => item.key === 'enter')
  const entryItem = buildEntryRouteItem(entry, ROUTE_ITEM_FALLBACK['route-entry'])

  return [...amenityItems, entryItem]
}

export default function DirectionsPage() {
  const { id } = useParams()
  const [venue, setVenue] = useState(null)
  const [config, setConfig] = useState(null)
  const [sports, setSports] = useState([])
  const [suburbs, setSuburbs] = useState([])
  const [error, setError] = useState('')
  const fallbackVenue = useMemo(
    () => HOME_VENUES.find((item) => String(item.id) === String(id)) ?? null,
    [id],
  )
  const displayVenue = venue ?? fallbackVenue

  useEffect(() => {
    let isMounted = true

    Promise.all([getVenue(id), getConfig(), getSports(), getSuburbs()])
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
  }, [id])

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
    }
  }, [config, displayVenue, sports, suburbs])

  const heroData = useMemo(
    () => ({
      eyebrow: 'Directions',
      title: displayVenue?.name ?? directionsPageData.hero.title,
      address: displayVenue ? formatAddress(displayVenue) : directionsPageData.hero.address,
      badge:
        venue?.last_updated
          ? `Data retrieved ${venue.last_updated}`
          : fallbackVenue?.distance
            ? `${fallbackVenue.distance} km from current search`
            : directionsPageData.hero.badge,
    }),
    [directionsPageData.hero.address, directionsPageData.hero.badge, directionsPageData.hero.title, displayVenue, fallbackVenue?.distance, venue?.last_updated],
  )

  const routeFacilities = useMemo(() => {
    const defaultDistance = config?.default_distance_m ?? 500
    return buildDirectionsFacilities(displayVenue, defaultDistance)
  }, [config?.default_distance_m, displayVenue])

  return (
    <AppShell
      backTo={`/venues/${id}`}
      backLabel={directionsPageData.backLabel}
      headline={directionsPageData.sidebarHeadline}
      sidebarChildren={
        <>
          <StaticSearchPanel data={sidebarData} />
        </>
      }
    >
      <DirectionsHero hero={heroData} />

      {displayVenue || !error ? (
        <section className="workspace">
          <StaticRouteMap
            mapData={directionsPageData.map}
            facilities={routeFacilities}
            sectionTitle={directionsPageData.directionsSectionTitle}
            sectionBody="Route-specific live details are not published yet. The items below connect the current venue-side information into your directions UI."
          />
        </section>
      ) : null}

      {error && !fallbackVenue ? (
        <section className="disclaimer-card">
          <h3>Directions unavailable</h3>
          <p>{error}</p>
        </section>
      ) : null}
    </AppShell>
  )
}
