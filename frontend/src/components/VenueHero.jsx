import { Link } from "react-router-dom";

export default function VenueHero({ hero, venueId }) {
  return (
    <section className="hero-card">
      <p className="eyebrow">{hero.eyebrow}</p>

      <div className="hero-top">
        <div className="hero-copy-main">
          <h2>{hero.title}</h2>
          <p>{hero.address}</p>
        </div>

        <div className="hero-top-actions">
          {hero.badge ? <div className="hero-badge hero-badge--success">{hero.badge}</div> : null}
          {venueId ? (
            <Link className="get-directions-button" to={`/venues/${venueId}/directions`}>
              Get directions
            </Link>
          ) : null}
        </div>
      </div>

      {hero.tags?.length ? (
        <div className="chips">
          {hero.tags.map((tag) => (
            <span key={tag} className="chip">
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      {hero.panels?.length ? (
        <div className="hero-summary">
          {hero.panels.map((panel) => (
            <div key={panel.label} className="hero-panel">
              <span>{panel.label}</span>
              {panel.emphasis ? <strong>{panel.emphasis}</strong> : null}
              <p>{panel.body}</p>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}