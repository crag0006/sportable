import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getConfig, getSports, getSuburbs, getVenue, getVenueCorridor } from '../api/venues'
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

function getCorridorIcon(type) {
  if (type === 'stop') return 'transport'
  return type
}

function getCorridorTag(facility) {
  if (facility.type === 'toilet' && typeof facility.mlak === 'boolean') {
    return facility.mlak ? 'Key required' : 'No key needed'
  }

  return 'Published'
}

function buildCorridorFacilityDescription(facility, typeLabel) {
  const subject = facility.name || typeLabel
  const address = facility.address ? ` at ${facility.address}` : ''
  return `${subject} is recorded ${facility.distance_from_path_m} m from the straight-line corridor${address}.`
}

function buildCorridorFacilityMeta(facility) {
  const rows = [
    { label: 'Travel order', value: `#${facility.seq}` },
    { label: 'Offset', value: `${facility.distance_from_path_m} m from line` },
    { label: 'Along line', value: `${facility.along_path_m} m from start` },
  ]

  if (facility.opening_hours) {
    rows.push({ label: 'Hours', value: facility.opening_hours })
  }

  if (typeof facility.mlak === 'boolean') {
    rows.push({ label: 'MLAK', value: facility.mlak ? 'Key required' : 'Not required' })
  }

  if (facility.source?.name) {
    rows.push({ label: 'Source', value: facility.source.name })
  }

  return rows
}

function buildCorridorStatusItems(corridor) {
  return (corridor?.types ?? [])
    .filter((typeItem) => typeItem.status !== 'found')
    .map((typeItem) => ({
      id: `corridor-${typeItem.type}-status`,
      title: typeItem.label,
      description:
        typeItem.status === 'none_within'
          ? `Published datasets were checked, but no ${typeItem.label.toLowerCase()} were found within ${corridor.path.within_m} m of the straight-line corridor.`
          : `No dataset for ${typeItem.label.toLowerCase()} is loaded yet, so this page cannot confirm availability.`,
      tag: typeItem.status === 'none_within' ? 'Checked' : 'No data',
      tagVariant: 'alert',
      icon: getCorridorIcon(typeItem.type),
      meta: [
        {
          label: 'Status',
          value: typeItem.status === 'none_within' ? 'Checked, none within corridor' : 'Dataset not loaded',
        },
      ],
    }))
}

function buildCorridorFacilities(corridor) {
  const typeLabels = Object.fromEntries((corridor?.types ?? []).map((typeItem) => [typeItem.type, typeItem.label]))

  const foundItems = [...(corridor?.facilities ?? [])]
    .sort((firstItem, secondItem) => firstItem.seq - secondItem.seq)
    .map((facility) => ({
      id: `corridor-facility-${facility.type}-${facility.seq}`,
      title: facility.name || typeLabels[facility.type] || facility.type,
      description: buildCorridorFacilityDescription(
        facility,
        typeLabels[facility.type] || facility.type,
      ),
      tag: getCorridorTag(facility),
      tagVariant: 'good',
      icon: getCorridorIcon(facility.type),
      meta: buildCorridorFacilityMeta(facility),
    }))

  return [...foundItems, ...buildCorridorStatusItems(corridor)]
}

function buildCorridorMapData(baseMap, corridor, displayStartLabel) {
  const firstFacility = corridor?.facilities?.[0]
  const lastFacility = corridor?.facilities?.[corridor.facilities.length - 1]
  const facilityPoints = (corridor?.facilities ?? []).map((facility) => ({
    seq: facility.seq,
    type: facility.type,
    lat: facility.lat,
    lon: facility.lon,
    label: facility.name || facility.type,
  }))

  return {
    ...baseMap,
    title: 'Straight-line corridor overview',
    summaryCards: [
      { label: 'Starting point', value: displayStartLabel || corridor.origin.label },
      { label: 'Straight-line distance', value: `${corridor.path.length_m} m` },
      { label: 'Corridor width', value: `${corridor.path.within_m} m` },
      { label: 'Facilities found', value: `${corridor.facilities.length} published` },
    ],
    callouts: [
      { key: 'station', label: displayStartLabel || corridor.origin.label, position: { x: 8, y: 16 } },
      {
        key: 'crossing',
        label: firstFacility?.name || lastFacility?.name || `${corridor.facilities.length} facilities checked`,
        position: { x: 42, y: 31 },
      },
      { key: 'venue', label: corridor.venue.name, position: { x: 78, y: 78 } },
    ],
    coordinates: corridor.path.coordinates,
    facilityPoints,
  }
}

function buildCorridorSectionBody(corridor, displayStartLabel) {
  return `Showing published facilities within ${corridor.path.within_m} m of the straight-line corridor from ${displayStartLabel || corridor.origin.label} to ${corridor.venue.name}.`
}

function buildRoutePlanItems({ displayStartLabel, displayVenue, facilities, corridor }) {
  const planItems = [...(facilities ?? [])]

  return [
    {
      id: 'route-plan-start',
      title: 'Start point',
      description: corridor?.origin?.label
        ? `Start from ${displayStartLabel}. Route calculations are anchored to ${corridor.origin.label}.`
        : `Start from ${displayStartLabel}.`,
      tag: 'Start',
      tagVariant: 'good',
      icon: 'start',
      meta: [
        {
          label: 'Origin',
          value: displayStartLabel,
        },
      ],
    },
    ...planItems,
    {
      id: 'route-plan-destination',
      title: 'Destination',
      description: `Arrive at ${displayVenue?.name || 'the venue'}${displayVenue ? `, ${formatAddress(displayVenue)}` : '.'}`,
      tag: 'Finish',
      tagVariant: 'good',
      icon: 'destination',
      meta: displayVenue
        ? [
            { label: 'Venue', value: displayVenue.name },
            { label: 'Address', value: formatAddress(displayVenue) },
          ]
        : [],
    },
  ]
}

export default function DirectionsPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const [venue, setVenue] = useState(null)
  const [corridor, setCorridor] = useState(null)
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

    Promise.all([
      getVenue(id, { from: fromQuery || undefined }),
      getConfig(),
      getSports(),
      getSuburbs(),
      fromQuery
        ? getVenueCorridor(id, {
            from: fromQuery,
            within: withinQuery || undefined,
          })
        : Promise.resolve(null),
    ])
      .then(([venueBody, configBody, sportsBody, suburbsBody, corridorBody]) => {
        if (!isMounted) return
        setVenue(venueBody)
        setCorridor(corridorBody)
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
  }, [fromQuery, id, withinQuery])

  const sidebarData = useMemo(() => {
    const defaultDistance = config?.default_distance_m
    const activeDistanceValue = withinQuery || (defaultDistance ? String(defaultDistance) : '')

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
      activeDistance: activeDistanceValue ? formatBandLabel(Number(activeDistanceValue)) : searchPanelData.activeDistance,
      destination: displayVenue?.name ?? searchPanelData.destination,
      startPoint: displayStartLabel,
      startPointOptions: ['Current location (test)', ...(suburbs.length > 0 ? suburbs : searchPanelData.suburbOptions)],
      currentPath: `/venues/${id}/directions`,
    }
  }, [config, displayStartLabel, displayVenue, id, sports, suburbs, withinQuery])

  const heroData = useMemo(
    () => ({
      eyebrow: 'Directions',
      title: displayVenue?.name ?? directionsPageData.hero.title,
      address: displayVenue ? formatAddress(displayVenue) : directionsPageData.hero.address,
      badge:
        venue?.distance && venue?.reference_point?.label
          ? `${venue.distance} km from ${venue.reference_point.label}`
          : venue?.last_updated
            ? `Data retrieved ${venue.last_updated}`
          : fallbackVenue?.distance
            ? `${fallbackVenue.distance} km from current search`
            : directionsPageData.hero.badge,
    }),
    [
      directionsPageData.hero.address,
      directionsPageData.hero.badge,
      directionsPageData.hero.title,
      displayVenue,
      fallbackVenue?.distance,
      venue?.distance,
      venue?.last_updated,
      venue?.reference_point?.label,
    ],
  )

  const routeFacilities = useMemo(() => {
    const defaultDistance = config?.default_distance_m ?? 500
    if (corridor) {
      return buildCorridorFacilities(corridor)
    }
    return buildDirectionsFacilities(displayVenue, defaultDistance)
  }, [config?.default_distance_m, corridor, displayVenue])

  const mapData = useMemo(() => {
    if (!corridor) return directionsPageData.map
    return buildCorridorMapData(directionsPageData.map, corridor, displayStartLabel)
  }, [corridor, displayStartLabel])

  const sectionBody = useMemo(() => {
    if (!corridor) {
      return 'Route-specific live details are not published yet. The items below connect the current venue-side information into your directions UI.'
    }

    return buildCorridorSectionBody(corridor, displayStartLabel)
  }, [corridor, displayStartLabel])

  const routePlanItems = useMemo(
    () =>
      buildRoutePlanItems({
        displayStartLabel,
        displayVenue,
        facilities: routeFacilities,
        corridor,
      }),
    [corridor, displayStartLabel, displayVenue, routeFacilities],
  )

  return (
    <AppShell
      backTo={`/venues/${id}${sharedQuery}`}
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
            mapData={mapData}
            facilities={routePlanItems}
            sectionTitle={directionsPageData.directionsSectionTitle}
            sectionBody={sectionBody}
          />
        </section>
      ) : null}

      {corridor ? (
        <section className="disclaimer-card">
          <h3>{directionsPageData.disclaimerTitle}</h3>
          <p>{directionsPageData.disclaimerBody}</p>
          {corridor.checked.map((sentence) => (
            <p key={sentence}>{sentence}</p>
          ))}
          {corridor.not_checked.map((sentence) => (
            <p key={sentence}>{sentence}</p>
          ))}
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
