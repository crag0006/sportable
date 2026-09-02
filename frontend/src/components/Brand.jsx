export default function Brand() {
  return (
    <section className="brand" aria-label="SportAble brand">
      <div className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32">
          <path d="M9 9.5c2.8-2.5 8.2-2.7 10.7-.2 2.1 2.1 1.8 5.6-.5 7.7l-6.8 6.1" />
          <path d="M10.5 16.5l4.2 4.2" />
          <path d="M19.2 10.2l3.3 3.3" />
        </svg>
      </div>
      <div>
        <p className="brand-name">SportAble</p>
        <p className="brand-tagline">KNOW MORE. PLAY MORE</p>
      </div>
    </section>
  )
}
