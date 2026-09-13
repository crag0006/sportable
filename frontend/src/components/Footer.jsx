import { Link } from "react-router-dom";
import "./Footer.css";

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="footer-grid">
          {/* Brand */}
          <div className="footer-col">
            <div className="footer-brand">
              <span aria-hidden="true">♿</span>
              <span className="footer-brand-name">SportAble</span>
            </div>
            <p className="footer-tagline">
              Helping people with mobility access needs find sports venues
              across Greater Melbourne — with real distances, not guesses.
            </p>
          </div>

          {/* Quick links */}
          <div className="footer-col">
            <h3 className="footer-heading">Explore</h3>
            <ul className="footer-links">
              <li><Link to="/">Home</Link></li>
              <li><Link to="/venues">Venue search</Link></li>
              <li><Link to="/events">Events</Link></li>
            </ul>
          </div>

          {/* Data & sources */}
          <div className="footer-col">
            <h3 className="footer-heading">Data &amp; sources</h3>
            <p className="footer-text">
              Facility information is drawn from the National Public Toilet
              Map, the Sport and Recreation Victoria facilities list, and
              the ASGS suburb layer. Distances shown are straight-line, not
              a walked path.
            </p>
          </div>

          {/* About / legal */}
          <div className="footer-col">
            <h3 className="footer-heading">About this project</h3>
            <ul className="footer-links">
              <li>Built for FIT5120 — IT Project, Monash University</li>              
            </ul>
          </div>
        </div>

        <div className="footer-bottom">
          <p>
            © {new Date().getFullYear()} SportAble Melbourne. Built as a
            student project — not an official government or council service.
          </p>
        </div>
      </div>
    </footer>
  );
}