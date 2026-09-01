export default function VenueHero({ hero }) {
  return (
    <section className="hero-card">
      <p className="eyebrow">{hero.eyebrow}</p>

      <div className="hero-top">
        <div className="hero-copy-main">
          <h2>{hero.title}</h2>
          <p>{hero.address}</p>
        </div>

        <div className="hero-badge hero-badge--success">{hero.badge}</div>
      </div>

      <div className="chips">
        {hero.tags.map((tag) => (
          <span key={tag} className="chip">
            {tag}
          </span>
        ))}
      </div>

      <div className="hero-summary">
        {hero.panels.map((panel) => (
          <div key={panel.label} className="hero-panel">
            <span>{panel.label}</span>
            {panel.emphasis ? <strong>{panel.emphasis}</strong> : null}
            <p>{panel.body}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
