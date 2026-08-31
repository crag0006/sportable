export const FACILITY_INFO = {
  toilet: {
    name: 'Toilet',
    fullName: 'Accessible toilet',
    icon: '🚻',
  },
  parking: {
    name: 'Parking',
    fullName: 'Accessible parking',
    icon: '🅿',
  },
  stop: {
    name: 'Transport',
    fullName: 'Step-free transport stop',
    icon: '🚋',
  },
  change: {
    name: 'Change facility',
    fullName: 'Accessible change facility',
    icon: '♿',
  },
}

export const SPORTS = ['Badminton', 'Basketball', 'Netball', 'Swimming', 'Tennis']

export const SUBURBS = [
  'Melbourne CBD 3000',
  'Carlton 3053',
  'Fitzroy 3065',
  'North Melbourne 3051',
  'Preston 3072',
  'Kensington 3031',
]

export const VENUES = [
  {
    id: 1,
    name: 'North Melbourne Recreation Centre',
    suburb: 'North Melbourne',
    postcode: '3051',
    sports: ['Basketball', 'Badminton', 'Netball'],
    surface: 'Indoor sprung timber',
    distance: 1.2,
    amenities: {
      toilet: { state: 'recorded', distance: 15 },
      parking: { state: 'recorded', distance: 58 },
      stop: { state: 'recorded', distance: 130 },
      change: { state: 'recorded', distance: 1200 },
    },
  },
  {
    id: 2,
    name: 'Carlton Baths',
    suburb: 'Carlton',
    postcode: '3053',
    sports: ['Swimming', 'Basketball'],
    surface: 'Indoor pool',
    distance: 2.4,
    amenities: {
      toilet: { state: 'recorded', distance: 40 },
      parking: { state: 'recorded', distance: 210 },
      stop: { state: 'recorded', distance: 95 },
      change: { state: 'none' },
    },
  },
  {
    id: 3,
    name: 'Kensington Community Courts',
    suburb: 'Kensington',
    postcode: '3031',
    sports: ['Basketball', 'Tennis'],
    surface: 'Outdoor acrylic',
    distance: 3.1,
    amenities: {
      toilet: { state: 'absent' },
      parking: { state: 'recorded', distance: 75 },
      stop: { state: 'recorded', distance: 180 },
      change: { state: 'none' },
    },
  },
  {
    id: 4,
    name: 'Preston City Oval',
    suburb: 'Preston',
    postcode: '3072',
    sports: ['Netball', 'Tennis'],
    surface: 'Outdoor grass',
    distance: 0.8,
    amenities: {
      toilet: { state: 'none' },
      parking: { state: 'none' },
      stop: { state: 'recorded', distance: 320 },
      change: { state: 'none' },
    },
  },
]

export const PLACE_NAMES = {
  3000: 'Melbourne CBD 3000',
  3053: 'Carlton 3053',
  3065: 'Fitzroy 3065',
  3051: 'North Melbourne 3051',
  3072: 'Preston 3072',
}
