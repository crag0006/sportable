export const searchPanelData = {
  title: 'Route setup',
  subtitle: 'Keep only the two core search locations visible by default.',
  sport: 'Basketball',
  suburbOrPostcode: 'North Melbourne 3051',
  sportOptions: ['Badminton', 'Basketball', 'Netball', 'Swimming', 'Tennis'],
  suburbOptions: [
    'Melbourne CBD 3000',
    'Carlton 3053',
    'Fitzroy 3065',
    'North Melbourne 3051',
    'Preston 3072',
    'Kensington 3031',
  ],
  amenityOptions: [
    'Accessible toilet',
    'Accessible parking',
    'Step-free transport stop',
    'Access entry',
  ],
  defaultSelectedAmenities: [
    'Accessible toilet',
    'Accessible parking',
    'Step-free transport stop',
    'Access entry',
  ],
  distanceOptions: ['250 m', '500 m', '1 km'],
  activeDistance: '1 km',
  startPoint: 'Melton Station accessible drop-off',
  destination: 'Melton Waves Leisure Centre',
}

export const weatherData = {
  temperature: '17°C',
  summary: 'Cloudy with light wind',
  stats: [
    { label: 'Feels like', value: '15°C' },
    { label: 'Rain', value: '20% chance' },
    { label: 'Dress', value: 'Light jacket recommended' },
    { label: 'Travel note', value: 'Footpaths likely dry' },
  ],
  tip: 'Mild weather for travel planning today. Bring a light outer layer and keep a compact umbrella only as backup.',
}

export const venueDetailData = {
  sidebarHeadline: 'Venue Information',
  backLabel: 'Back to venue home',
  backTo: '/',
  hero: {
    eyebrow: 'Venue detail',
    title: 'North Melbourne Recreation Centre',
    address: '2 Coburns Road, Melton VIC 3337',
    badge: 'Access details reviewed 12 Aug 2026',
    tags: [
      'Swimming',
      'Wheelchair basketball',
      'Group fitness',
      'Recreation',
      'Community venue',
    ],
    panels: [
      {
        label: 'Venue summary',
        body: 'Community aquatic and recreation venue with indoor courts, pool access, accessible parking, and multiple practical arrival options surfaced in the same product language as the homepage results.',
      },
      {
        label: 'Nearest accessible bay',
        emphasis: '48 m',
        body: 'North entry parking cluster',
      },
    ],
  },
  mapPreview: {
    label: 'Map preview',
    caption: 'This thumbnail matches the route map used on the directions page.',
    linkLabel: 'Linked map',
  },
  facilitiesSectionTitle: 'Facilities',
}

export const venueFacilities = [
  {
    id: 'parking',
    title: 'Accessible parking',
    description: 'Primary arrival option closest to the north entry and ticketing foyer.',
    distance: '48 m',
    source: 'Council venue audit',
    updated: '12 Aug 2026',
    thirdLabel: 'Hours',
    thirdValue: 'During venue opening hours',
    location: 'Main car park, north entry',
    icon: 'parking',
  },
  {
    id: 'toilet',
    title: 'Accessible toilet',
    description: 'Ground-floor option near aquatic foyer with confirmed staff guidance available.',
    distance: '62 m',
    source: 'Staff confirmation',
    updated: '09 Aug 2026',
    thirdLabel: 'MLAK',
    thirdValue: 'Key required',
    location: 'Aquatic foyer, ground floor',
    icon: 'toilet',
  },
  {
    id: 'entry',
    title: 'Ramp entry',
    description: 'Most direct step-free pedestrian entry from drop-off and parking approach.',
    distance: '12 m',
    source: 'On-site review',
    updated: '12 Aug 2026',
    thirdLabel: 'Hours',
    thirdValue: 'Always available',
    location: 'Western pedestrian entrance',
    icon: 'ramp',
  },
  {
    id: 'hoist',
    title: 'Pool hoist',
    description: 'Warm-water pool support equipment available with trained staff assistance.',
    distance: '96 m',
    source: 'Aquatic operations log',
    updated: '05 Aug 2026',
    thirdLabel: 'Hours',
    thirdValue: '9:00 AM – 5:00 PM',
    location: 'Not required',
    locationLabel: 'MLAK',
    icon: 'hoist',
  },
]

export const directionsPageData = {
  sidebarHeadline: 'Directions',
  backLabel: 'Back to venue home',
  backTo: '/venues/1',
  hero: {
    eyebrow: 'Directions',
    title: 'North Melbourne Recreation Centre',
    address: '48 Buncle Street, North Melbourne VIC 3051',
    badge: 'Estimated accessible travel time: 18 minutes',
  },
  map: {
    title: 'Map overview',
    summaryCards: [
      { label: 'Step-free segments', value: '4 confirmed' },
      { label: 'Steeper section', value: '1 moderate incline' },
      { label: 'Fallback option', value: 'North entry parking' },
    ],
    callouts: [
      { key: 'station', label: 'Station drop-off' },
      { key: 'crossing', label: 'Signalised crossing' },
      { key: 'venue', label: 'Venue entry' },
    ],
  },
  directionsSectionTitle: 'Directions and facilities',
  directionsSectionBody: '',
  disclaimerTitle: 'Travel disclaimer',
  disclaimerBody:
    'This route is intended as an access-planning aid. Distances, public path conditions, and facility availability should still be checked against the latest venue or council information before travel.',
}

export const directionsFacilities = [
  {
    id: 'route-toilet',
    title: 'Accessible toilets and facility',
    description:
      'Accessible toilet is available along the route corridor, and the synchronized venue detail confirms the MLAK key requirement before arrival.',
    tag: 'Key required',
    tagVariant: 'alert',
    icon: 'toilet',
    meta: [
      { label: 'Distance', value: '62 m' },
      { label: 'MLAK', value: 'Key required' },
      { label: 'Location', value: 'Aquatic foyer' },
    ],
  },
  {
    id: 'route-parking',
    title: 'Accessible parking',
    description:
      'Accessible parking bays are located near the north-side approach, providing a closer fallback arrival option for users travelling by car.',
    tag: 'Confirmed',
    tagVariant: 'good',
    icon: 'parking',
    meta: [
      { label: 'Distance', value: '48 m' },
      { label: 'Hours', value: 'Venue hours' },
      { label: 'Location', value: 'North entry' },
    ],
  },
  {
    id: 'route-stop',
    title: 'Step-free public transport stops',
    description:
      'Nearest public transport stop connects to the route with step-free footpath segments, kerb ramps, and a direct approach toward the venue side.',
    tag: 'Confirmed',
    tagVariant: 'good',
    icon: 'transport',
    meta: [
      { label: 'Distance', value: '130 m' },
      { label: 'Access', value: 'Step-free' },
      { label: 'Stop type', value: 'Bus stop' },
    ],
  },
  {
    id: 'route-entry',
    title: 'Access entry',
    description:
      'Main accessible entry uses a step-free approach with clearer threshold access, making it the preferred arrival point once users reach the venue.',
    tag: 'Preferred entry',
    tagVariant: 'good',
    icon: 'ramp',
    meta: [
      { label: 'Distance', value: '12 m' },
      { label: 'Threshold', value: 'Step-free' },
      { label: 'Location', value: 'West entry' },
    ],
  },
]
