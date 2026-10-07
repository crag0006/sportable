import TopBar from "../components/TopBar";
import { Link } from "react-router-dom";
import "./LandingPage.css";
import Footer from "../components/Footer";

function Landing() {
  return (
    <div className="landing-page">
      
      <TopBar links={[]} />

      <div className="landing">
        <div className="landing-shade">
          <main className="landing-main">
            <h1 className="landing-headline">
              Find a sports venue or event that works for you.
            </h1>

            <p className="landing-intro">
              Search sports venues and events, and check nearby accessibility facilities before you travel.
            </p>

            <div className="landing-buttons">
              <Link to="/venues" className="landing-btn landing-btn--primary">
                Find a Venue
              </Link>
              <Link to="/events" className="landing-btn landing-btn--secondary">
                Find an Event
              </Link>
            </div>
          </main>
        </div>
      </div>

      <Footer/>
    </div>
  );
}

export default Landing;