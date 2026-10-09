import { useState } from "react";
import "./AddToCalendarButton.css";
import {
  buildCalendarEventPayload,
  createGoogleCalendarEvent,
  hasAddedToCalendarThisSession,
  markAddedToCalendarThisSession,
} from "./GoogleCalendar";

const DEFAULT_DURATION_MS = 2 * 60 * 60 * 1000; 

function toTimeInputValue(date) {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function combineDateAndTime(dateLocal, timeString) {
  return new Date(`${dateLocal}T${timeString}:00`);
}

const FACILITY_LABELS = {
  accessible_toilet: "Accessible toilet",
  accessible_parking: "Accessible parking",
  accessible_transport_stop: "Accessible transport",
  accessible_change_facility: "Accessible change facility",
};


export default function AddToCalendarButton({ event }) {
  const canAdd = Boolean(event.dateLocal && event.timeLocal);

  const [step, setStep] = useState("closed"); 
  const [title, setTitle] = useState(event.title);
  const [endTime, setEndTime] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [resultLink, setResultLink] = useState("");

  if (!canAdd) {
    return (
      <p className="calendar-unavailable-note">
        Can't add to calendar — this event's date and time aren't published yet.
      </p>
    );
  }

  const startDate = combineDateAndTime(event.dateLocal, event.timeLocal);

  function openPreview() {
    setTitle(event.title);
    setEndTime(toTimeInputValue(new Date(startDate.getTime() + DEFAULT_DURATION_MS)));
    setErrorMessage("");
    setStep("preview");
  }

  function closeModal() {
    if (step === "sending") return; 
    setStep("closed");
  }

  function handleConfirm() {
    
    if (hasAddedToCalendarThisSession(event.id)) {
      setStep("duplicate");
      return;
    }
    submit();
  }

  async function submit() {
    setStep("sending");
    setErrorMessage("");

    const endDate = combineDateAndTime(event.dateLocal, endTime);

    try {
      const payload = buildCalendarEventPayload({
        title: title.trim() || event.title,
        startDate,
        endDate,
        venueName: event.venueName,
        venueAddress: event.venueAddress,
        venueHref: event.venueHref,
        facilities: event.facilities,
      });

      const created = await createGoogleCalendarEvent(payload);

      markAddedToCalendarThisSession(event.id);
      setResultLink(created.htmlLink || "");
      setStep("success");
    } catch (error) {
      setErrorMessage(
        error.message || "Something went wrong adding this to your calendar."
      );
      setStep("error");
    }
  }

  return (
    <>
      <button
        type="button"
        className="event-action-link event-action-link--secondary calendar-add-button"
        onClick={openPreview}
        style={{
          appearance: "none",
          WebkitAppearance: "none",
          MozAppearance: "none",
          font: "inherit",
          lineHeight: "inherit",
          boxSizing: "border-box",
          cursor: "pointer",
          alignSelf: "center",
        }}
      >
        <span aria-hidden="true">📅</span> Add to Google Calendar
      </button>

      {step !== "closed" && (
        <div
          className="calendar-modal-overlay"
          onClick={(domEvent) => {
            if (domEvent.target === domEvent.currentTarget) closeModal();
          }}
        >
          <div
            className="calendar-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Add to Google Calendar"
            onKeyDown={(domEvent) => {
              if (domEvent.key === "Escape") closeModal();
            }}
          >
            {step === "preview" && (
              <>
                <h3 className="calendar-modal-title">Add to Google Calendar</h3>
                <p className="calendar-modal-subtitle">
                  Check the details below, then confirm — nothing is sent to
                  Google until you do.
                </p>

                <label className="calendar-field">
                  <span>Title</span>
                  <input
                    type="text"
                    value={title}
                    onChange={(domEvent) => setTitle(domEvent.target.value)}
                  />
                </label>

                <div className="calendar-field-row">
                  <div className="calendar-field calendar-field--readonly">
                    <span>Date</span>
                    <p>
                      {startDate.toLocaleDateString("en-AU", {
                        weekday: "short",
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </p>
                  </div>

                  <div className="calendar-field calendar-field--readonly">
                    <span>Start time</span>
                    <p>
                      {startDate.toLocaleTimeString("en-AU", {
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>

                  <label className="calendar-field">
                    <span>End time</span>
                    <input
                      type="time"
                      value={endTime}
                      onChange={(domEvent) => setEndTime(domEvent.target.value)}
                    />
                  </label>
                </div>

                <div className="calendar-field calendar-field--readonly">
                  <span>Venue</span>
                  <p>
                    {event.venueName}
                    {event.venueAddress ? `, ${event.venueAddress}` : ""}
                  </p>
                </div>

                {event.facilities && event.facilities.length > 0 && (
                  <div className="calendar-field calendar-field--readonly">
                    <span>Accessibility (included in the event description)</span>
                    <ul className="calendar-facility-list">
                      {event.facilities.map((facility) => (
                        <li key={facility.type}>
                          {FACILITY_LABELS[facility.type] || facility.type}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="calendar-modal-actions">
                  <button type="button" className="calendar-btn-secondary" onClick={closeModal}>
                    Cancel
                  </button>
                  <button type="button" className="calendar-btn-primary" onClick={handleConfirm}>
                    Add to calendar
                  </button>
                </div>
              </>
            )}

            {step === "duplicate" && (
              <>
                <h3 className="calendar-modal-title">Already added</h3>
                <p className="calendar-modal-subtitle">
                  You've already added "{event.title}" to your Google Calendar
                  during this visit. Adding it again will create a second,
                  separate entry.
                </p>
                <div className="calendar-modal-actions">
                  <button type="button" className="calendar-btn-secondary" onClick={() => setStep("preview")}>
                    Cancel
                  </button>
                  <button type="button" className="calendar-btn-primary" onClick={submit}>
                    Add anyway
                  </button>
                </div>
              </>
            )}

            {step === "sending" && (
              <div className="calendar-status">
                <div className="calendar-spinner" aria-hidden="true" />
                <p>Adding to your Google Calendar…</p>
              </div>
            )}

            {step === "success" && (
              <div className="calendar-status">
                <p className="calendar-status-heading">
                  ✓ Added "{title}" to your calendar
                </p>
                <p>
                  {startDate.toLocaleDateString("en-AU", {
                    weekday: "long",
                    day: "numeric",
                    month: "long",
                  })}
                </p>
                {resultLink && (
                  <a
                    href={resultLink}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="calendar-btn-primary calendar-open-link"
                  >
                    Open in Google Calendar
                  </a>
                )}
                <button type="button" className="calendar-btn-secondary" onClick={closeModal}>
                  Done
                </button>
              </div>
            )}

            {step === "error" && (
              <div className="calendar-status">
                <p className="calendar-status-heading calendar-status-heading--error">
                  Couldn't add this to your calendar
                </p>
                <p>{errorMessage}</p>
                <p className="calendar-status-note">
                  Your saved event hasn't changed — you can try again any time.
                </p>
                <div className="calendar-modal-actions">
                  <button type="button" className="calendar-btn-secondary" onClick={closeModal}>
                    Close
                  </button>
                  <button type="button" className="calendar-btn-primary" onClick={() => setStep("preview")}>
                    Try again
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
