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
              No limits. Just possibilities.
            </h1>

            <p className="landing-intro">
              SportAble helps people with mobility access needs find
              sports venues across Greater Melbourne. Instead of a
              yes or no, we show the measured distance to the
              facilities you depend on.
            </p>

            <div className="landing-buttons">
              <Link to="/venues" className="landing-btn landing-btn--primary">
                Venue search
              </Link>
              <Link to="/events" className="landing-btn landing-btn--secondary">
                Events
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