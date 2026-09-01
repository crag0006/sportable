import { Link } from 'react-router-dom'

export default function MiniMapLinkCard({ label, caption, linkLabel, to }) {
  return (
    <section className="mini-note-card">
      <span className="side-label">{label}</span>

      <Link className="mini-map-anchor" to={to}>
        <div className="mini-map-panel" aria-label="Linked route map preview">
          <div className="mini-map-grid" />
          <div className="mini-road one" />
          <div className="mini-road two" />
          <div className="mini-road three" />
          <div className="mini-route" />
          <div className="mini-marker start">S</div>
          <div className="mini-marker end">V</div>
        </div>

        <div className="mini-map-caption">
          <span>{caption}</span>
          <span className="mini-map-link">{linkLabel}</span>
        </div>
      </Link>
    </section>
  )
}
