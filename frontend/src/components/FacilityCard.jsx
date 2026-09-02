import { FacilityEmoji } from './Icons'

export default function FacilityCard({ facility }) {
  const metaItems =
    facility.metaItems ??
    [
      { label: 'Source', value: facility.source || '—' },
      { label: 'Updated', value: facility.updated || '—' },
      {
        label: facility.thirdLabel || 'Detail',
        value: facility.thirdValue || '—',
      },
      {
        label: facility.locationLabel ?? 'Location',
        value: facility.location || '—',
      },
    ]

  return (
    <article className="facility-card">
      <div className="facility-icon">
        <FacilityEmoji icon={facility.icon} />
      </div>

      <div>
        <div className="facility-top">
          <div>
            <h3>{facility.title}</h3>
            <p>{facility.description}</p>
          </div>

          <div className="distance-pill">{facility.pillText || facility.distance || '—'}</div>
        </div>

        <div className="meta-grid">
          {metaItems.map((item) => (
            <div className="meta" key={`${facility.id}-${item.label}`}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      </div>
    </article>
  )
}
