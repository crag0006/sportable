import { Link } from "react-router-dom";
import "./TopBar.css";

// The same bar sits at the top of every page. Keeping it in one file
// means it cannot drift apart between pages.
// "links" is a list like [{ to: "/venues", label: "Venue search" }]
function TopBar({ links }) {
  return (
    <header className="site-topbar">
      <div className="site-topbar-inner">
        <Link to="/" className="site-brand">
          <svg
            width="34"
            height="34"
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
            <div className="site-brand-name">SportAble</div>
            <div className="site-brand-tagline">Know more. Play more.</div>
          </div>
        </Link>

        <nav className="site-nav" aria-label="Main">
          {links.map((link) => (
            <Link key={link.to} to={link.to} className="site-nav-link">
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

export default TopBar;