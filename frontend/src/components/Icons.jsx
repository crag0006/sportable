export function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 9l6 6 6-6" />
    </svg>
  )
}

export function ArrowLeftIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M15 18l-6-6 6-6" />
    </svg>
  )
}

export function CloudIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 18h9a4 4 0 0 0 .2-8A5.5 5.5 0 0 0 6 11.1 3.5 3.5 0 0 0 7 18" />
      <path d="M9 4.5v2" />
      <path d="M4.8 6.3l1.4 1.4" />
    </svg>
  )
}

export function ZoomInIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  )
}

export function ZoomOutIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14" />
    </svg>
  )
}

export function LocateIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 2v3" />
      <path d="M12 19v3" />
      <path d="M2 12h3" />
      <path d="M19 12h3" />
    </svg>
  )
}

export function FacilityIconGlyph({ icon }) {
  const shared = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: '1.8',
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
  }

  switch (icon) {
    case 'parking':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true" {...shared}>
          <path d="M4 15h16" />
          <path d="M6.5 15V9.5h11V15" />
          <circle cx="8.5" cy="17.5" r="1.5" />
          <circle cx="15.5" cy="17.5" r="1.5" />
        </svg>
      )
    case 'toilet':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true" {...shared}>
          <path d="M7 11.5h10" />
          <path d="M9 8.5v6" />
          <path d="M15 8.5v6" />
          <path d="M5.5 18.5h13" />
        </svg>
      )
    case 'ramp':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true" {...shared}>
          <path d="M5 16h14" />
          <path d="M6 16l4-8h8" />
          <path d="M14 8l3 5" />
        </svg>
      )
    case 'hoist':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true" {...shared}>
          <path d="M6 12h12" />
          <path d="M8 15c1.4 1.3 2.6 2 4 2s2.6-.7 4-2" />
          <path d="M8 9c1.4-1.3 2.6-2 4-2s2.6.7 4 2" />
          <path d="M5 19h14" />
        </svg>
      )
    case 'transport':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true" {...shared}>
          <rect x="5" y="7" width="14" height="10" rx="2" />
          <path d="M8 17v2" />
          <path d="M16 17v2" />
          <path d="M8 11h8" />
        </svg>
      )
    case 'change':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true" {...shared}>
          <circle cx="9" cy="5.5" r="1.8" />
          <path d="M9 8v5.2" />
          <path d="M9 10.5l4.2 2.2" />
          <path d="M9 13.2l-2.6 4.3" />
          <path d="M13 12.8l2.8 4.7" />
          <circle cx="16.8" cy="17.2" r="2.4" />
        </svg>
      )
    default:
      return null
  }
}
