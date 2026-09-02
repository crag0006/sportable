export default function Brand() {
  return (
    <section className="brand" aria-label="SportAble brand">
      <svg
        className="brand-logo"
        width="40"
        height="40"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="11" cy="4" r="2" />
        <path d="M11 8v6h5l3 6" />
        <path d="M15.5 14a5.5 5.5 0 1 1-6-5.48" />
      </svg>
      <div>
        <p className="brand-name">SportAble</p>
        <p className="brand-tagline">Know more. Play more.</p>
      </div>
    </section>
  )
}
