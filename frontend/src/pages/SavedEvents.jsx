import { useState } from "react";
import { Link } from "react-router-dom";
import TopBar from "../components/TopBar";
import "./SavedEvents.css";
import {
  getSavedEvents,
  removeSavedEvent,
  buildSavedEventsExportText,
} from "../components/savedEvents";

function downloadTextFile(filename, text) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function SavedEvents() {
  const [savedEvents, setSavedEvents] = useState(() => getSavedEvents());

  function handleRemove(eventId) {
    setSavedEvents(removeSavedEvent(eventId));
  }

  function handleExport() {
    const text = buildSavedEventsExportText(savedEvents);
    downloadTextFile("sportable-saved-events.txt", text);
  }

  return (
    <div className="search-page">
      <TopBar
        links={[
          { to: "/", label: "Home" },
          { to: "/events", label: "Events" },
        ]}
      />

      <main className="search-content">
        <section className="search-card">
          <h1 className="search-title">Saved events</h1>

          <p className="saved-events-note">
            Saved events are kept only for this visit — they'll be gone once
            you close this browser tab. Select "Export" if you want to keep
            a copy.
          </p>

          {savedEvents.length > 0 && (
            <button
              type="button"
              className="search-button saved-events-export-button"
              onClick={handleExport}
            >
              Export saved events
            </button>
          )}
        </section>

        {savedEvents.length === 0 ? (
          <section className="results-empty">
            <h2>No saved events yet</h2>
            <p>
              Find an event and select "Save" on its card to add it here.
              Saved events are only kept for this visit.
            </p>
            <Link
              to="/events"
              className="search-button saved-events-browse-link"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                textDecoration: "none",
              }}
            >
              Browse events
            </Link>
          </section>
        ) : (
          <div className="results">
            <div className="results-heading">
              <div>
                <h2>
                  {savedEvents.length} saved event
                  {savedEvents.length === 1 ? "" : "s"}
                </h2>
              </div>
            </div>

            {savedEvents.map((item) => (
              <article key={item.id} className="event-card saved-event-card">
                <div className="event-top">
                  <div>
                    <span className="chip">{item.sport}</span>
                    <h3 className="event-teams">{item.title}</h3>
                  </div>

                  <span className="event-datetime">
                    {item.dateTimeLabel || "Date to be confirmed"}
                  </span>
                </div>

                <div className="event-venue">
                  <div>
                    <p className="event-venue-name">{item.venueName}</p>
                    {item.suburb && (
                      <p className="event-venue-address">{item.suburb}</p>
                    )}
                  </div>
                </div>

                <div className="event-actions">
                  <button
                    type="button"
                    className="saved-event-remove-button"
                    onClick={() => handleRemove(item.id)}
                    aria-label={`Unsave ${item.title}`}
                  >
                    Unsave
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

export default SavedEvents;
