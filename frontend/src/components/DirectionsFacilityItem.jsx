import { FacilityEmoji } from './Icons'

export default function DirectionsFacilityItem({ item, stepNumber, isLast = false }) {
  const metaItems = (item.meta ?? []).filter(
    (metaItem) => metaItem && metaItem.label && metaItem.value,
  )

  return (
    <article className="route-item">
      <div className="route-step-rail" aria-hidden="true">
        <div className="route-step-number">{stepNumber}</div>
        {!isLast ? <div className="route-step-line" /> : null}
      </div>

      <div className="route-item-icon">
        <FacilityEmoji icon={item.icon} />
      </div>

      <div>
        <div className="route-item-top">
          <div>
            <h4>{item.title}</h4>
            <p>{item.description}</p>
          </div>

          {item.tag ? <span className={`item-tag item-tag--${item.tagVariant}`}>{item.tag}</span> : null}
        </div>

        {metaItems.length > 0 ? (
          <div className="route-meta">
            {metaItems.map((metaItem) => (
              <div key={metaItem.label} className="meta">
                <span>{metaItem.label}</span>
                <strong>{metaItem.value}</strong>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}
