export default function DirectionsHero({ hero }) {
  return (
    <section className="hero-card">
      <p className="eyebrow">{hero.eyebrow}</p>
      <h2>{hero.title}</h2>
      <p>{hero.address}</p>
      <div className="hero-badge hero-badge--success">{hero.badge}</div>
    </section>
  )
}
