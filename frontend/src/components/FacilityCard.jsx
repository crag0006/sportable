import { FacilityIconGlyph } from './Icons'

export default function FacilityCard({ facility }) {
  return (
    <article className="facility-card">
      <div className="facility-icon">
        <FacilityIconGlyph icon={facility.icon} />
      </div>

      <div>
        <div className="facility-top">
          <div>
            <h3>{facility.title}</h3>
            <p>{facility.description}</p>
          </div>

          <div className="distance-pill">{facility.distance}</div>
        </div>

        <div className="meta-grid">
          <div className="meta">
            <span>Source</span>
            <strong>{facility.source}</strong>
          </div>
          <div className="meta">
            <span>Updated</span>
            <strong>{facility.updated}</strong>
          </div>
          <div className="meta">
            <span>{facility.thirdLabel}</span>
            <strong>{facility.thirdValue}</strong>
          </div>
          <div className="meta">
            <span>{facility.locationLabel ?? 'Location'}</span>
            <strong>{facility.location}</strong>
          </div>
        </div>
      </div>
    </article>
  )
}
