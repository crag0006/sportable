import { FacilityIconGlyph } from './Icons'

export default function DirectionsFacilityItem({ item }) {
  return (
    <article className="route-item">
      <div className="route-item-icon">
        <FacilityIconGlyph icon={item.icon} />
      </div>

      <div>
        <div className="route-item-top">
          <div>
            <h4>{item.title}</h4>
            <p>{item.description}</p>
          </div>

          <span className={`item-tag item-tag--${item.tagVariant}`}>{item.tag}</span>
        </div>

        <div className="route-meta">
          {item.meta.map((metaItem) => (
            <div key={metaItem.label} className="meta">
              <span>{metaItem.label}</span>
              <strong>{metaItem.value}</strong>
            </div>
          ))}
        </div>
      </div>
    </article>
  )
}
