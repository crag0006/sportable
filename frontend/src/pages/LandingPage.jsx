import TopBar from "../components/TopBar";
import "./LandingPage.css";

function Landing() {
  return (
    <div>
      <TopBar
        links={[
          { to: "/venues", label: "Venue search" },
          { to: "/events", label: "Events" },
        ]}
      />

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
          </main>
        </div>
      </div>

      <footer className="landing-foot">
        <p>
          Built with Victorian open data. Always confirm access
          details with the venue before travelling.
        </p>
      </footer>
    </div>
  );
}

export default Landing;