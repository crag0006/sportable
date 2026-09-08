const API_BASE = '/api/v1'

const FACILITY_TYPE_BY_KEY = {
  toilet: 'accessible_toilet',
  parking: 'accessible_parking',
  stop: 'accessible_transport_stop',
  change: 'accessible_change_facility',
}

async function getJSON(path) {
  let response

  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new Error('Could not reach the SportAble service.')
  }

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const message = body?.error?.message || `Request failed (${response.status})`
    throw new Error(message)
  }

  return body
}

export function getVenue(id) {
  return getJSON(`/venues/${encodeURIComponent(id)}`)
}

export function getConfig() {
  return getJSON('/config').then((data) => ({
    distanceBandsM: data.distance_bands_m,
    defaultDistanceM: data.default_distance_m,
    maxResults: data.max_results,
  }))
}

export function getSports() {
  return getJSON('/sports').then((body) =>
    (body.sports ?? []).map((sport) => (typeof sport === 'string' ? sport : sport.name)),
  )
}

export function getSuburbs() {
  return getJSON('/suburbs').then((body) =>
    (body.suburbs ?? []).map((item) => item.label),
  )
}

export function getCorridor(venueId, from) {
  const params = new URLSearchParams({ from })
  return getJSON(`/venues/${encodeURIComponent(venueId)}/corridor?${params.toString()}`)
}

export function searchVenues({ sport, suburb, toilet, parking, stop, change, limit }) {
  const params = new URLSearchParams()
  params.set('sport', sport)

  const suburbInput = suburb.trim()
  const postcodeMatch = suburbInput.match(/(\d{4})\s*$/)

  if (postcodeMatch) {
    params.set('postcode', postcodeMatch[1])
  } else {
    params.set('suburb', suburbInput)
  }

  const facilityTypes = []
  if (toilet) facilityTypes.push(FACILITY_TYPE_BY_KEY.toilet)
  if (parking) facilityTypes.push(FACILITY_TYPE_BY_KEY.parking)
  if (stop) facilityTypes.push(FACILITY_TYPE_BY_KEY.stop)
  if (change) facilityTypes.push(FACILITY_TYPE_BY_KEY.change)

  if (facilityTypes.length > 0) {
    params.set('facilities', facilityTypes.join(','))
  }

  if (limit) {
    params.set('distance_m', limit)
  }

  return getJSON(`/venues/search?${params.toString()}`).then((data) => ({
    total: data.total,
    matched: data.matched,
    undocumented: data.undocumented,
    undocumentedLabel: null,
    place: data.reference_point?.label || data.place,
    distanceLimitM: data.distance_limit_m,
  }))
}
