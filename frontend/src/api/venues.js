const BASE = import.meta.env.VITE_API_BASE || ''

async function request(path) {
  let response

  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new Error('Could not reach the SportAble service.')
  }

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const message = body?.error?.message
    throw new Error(message || `The service returned an error (${response.status}).`)
  }

  return body
}

export function getVenue(id) {
  return request(`/api/v1/venues/${encodeURIComponent(id)}`)
}

export function getConfig() {
  return request('/api/v1/config')
}

export function getSports() {
  return request('/api/v1/sports').then((body) => body.sports ?? [])
}

export function getSuburbs() {
  return request('/api/v1/suburbs').then((body) => body.suburbs?.map((item) => item.label) ?? [])
}
