import { useState } from "react";
import "./AddToCalendarButton.css";
import {
  buildCalendarEventPayload,
  buildWeeklyRecurrenceRule,
  createGoogleCalendarEvent,
  hasAddedToCalendarThisSession,
  markAddedToCalendarThisSession,
} from "./googleCalendar";
import {
  extractPublishedTimeQuote,
  formatWeekday,
  suggestedStartTimeFromActivityWhen,
  todayCheckedLabel,
} from "./activityTime";

const DEFAULT_DURATION_MINUTES = 120; // 2 hours — our own fallback guess.
// The backend's §7.7 calendar block ships its own default (60 min) and is
// preferred wherever it's present; see openPreview().
const WEEKDAY_NAMES = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
];

function toTimeInputValue(date) {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function toDateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// Combines a "YYYY-MM-DD" date string with a "HH:MM" time string into a
// Date, in the browser's local timezone (events are Melbourne-local).
function combineDateAndTime(dateString, timeString) {
  return new Date(`${dateString}T${timeString}:00`);
}

function addMinutesToTimeString(timeString, minutes) {
  const [hours, mins] = timeString.split(":").map(Number);
  const date = new Date(2000, 0, 1, hours, mins);
  date.setMinutes(date.getMinutes() + minutes);
  return toTimeInputValue(date);
}

// The next date (today or later) that falls on the given weekday name —
// used as the default "starts from" date for a recurring activity, when
// the calendar block doesn't already give us `first_date`.
function nextDateForWeekday(weekdayName) {
  const targetIndex = WEEKDAY_NAMES.indexOf(weekdayName);
  if (targetIndex === -1) return new Date();

  const today = new Date();
  const diff = (targetIndex - today.getDay() + 7) % 7;
  const result = new Date(today);
  result.setDate(today.getDate() + diff);
  return result;
}

function parseLocalDate(dateString) {
  if (!dateString) return null;
  return new Date(`${dateString}T00:00:00`);
}

const FACILITY_LABELS = {
  accessible_toilet: "Accessible toilet",
  accessible_parking: "Accessible parking",
  accessible_transport_stop: "Accessible transport",
  accessible_change_facility: "Accessible change facility",
};

// event is a saved-events entry — see the shape note in Events.jsx's
// handleToggleSave. Two shapes are handled:
//
//  - event.calendarBlock set: the API already sent the §7.7 `calendar`
//    block (contract v0.3, once `feature/event-calendar-v03` is live).
//    That block is the single source of truth — exportability, the RRULE,
//    the time hint and the description all come from it, nothing is
//    recomputed. The primary action is the backend's own Google template
//    link(s) (no OAuth, no modal — Google's own page is the preview). The
//    OAuth modal below still works as a secondary option, but reads its
//    recurrence/time/description from this block instead of building them.
//
//  - event.calendarBlock null: today's production shape. Falls back to the
//    original logic — a fixed date+time, or a published weekday with the
//    time read (never parsed) from the description, confirmed by the user
//    in the OAuth modal, which is the only path available in this case.
//
// With neither a calendar block nor a usable date, this shows the "can't
// be added" note (AC5.1.5).
export default function AddToCalendarButton({ event }) {
  const calendarBlock = event.calendarBlock || null;
  const hasCalendarBlock = Boolean(calendarBlock);

  const hasFixedDateTime = Boolean(event.dateLocal && event.timeLocal);
  const hasLegacyRecurrence = Boolean(event.weekday);

  const canAdd = hasCalendarBlock
    ? calendarBlock.exportable
    : hasFixedDateTime || hasLegacyRecurrence;

  const [step, setStep] = useState("closed"); // closed | preview | duplicate | sending | success | error
  const [title, setTitle] = useState(event.title);
  const [endTime, setEndTime] = useState("");
  const [recurStartDate, setRecurStartDate] = useState("");
  const [recurStartTime, setRecurStartTime] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [resultLink, setResultLink] = useState("");
  const [templateClicked, setTemplateClicked] = useState(() =>
    hasCalendarBlock && calendarBlock.dedupe_key
      ? hasAddedToCalendarThisSession(calendarBlock.dedupe_key)
      : false
  );

  if (!canAdd) {
    const message = hasCalendarBlock
      ? calendarBlock.message
      : "Can't add to calendar — this event's date and time aren't published yet.";
    return <p className="calendar-unavailable-note">{message}</p>;
  }

  const fixedStartDate = hasFixedDateTime
    ? combineDateAndTime(event.dateLocal, event.timeLocal)
    : null;
  const isRecurring = !hasFixedDateTime;

  // Same link serves two jobs below: it's the "source" to cite next to a
  // quoted time, and the "contact" to point at when no time was published
  // at all. Only used on the no-calendar-block (legacy) path.
  const contactLink = event.registrationLink || event.externalLink || null;

  // The ONLY place description text is read for a legacy recurring
  // activity — to show the organiser's own words, never to compute a real
  // time from them. Not needed when calendarBlock is present: the backend
  // already did this (regex, then model on demand) and sends the result
  // as calendarBlock.time_hint.
  const publishedTimeQuote =
    !hasCalendarBlock && isRecurring
      ? extractPublishedTimeQuote(event.description)
      : null;
  const checkedDateLabel = todayCheckedLabel();

  // --- The backend's own "click and Save in Google" links -------------
  // google_template_urls[] has one URL per time slot; fall back to the
  // single google_template_url when there's only one. Paired with
  // time_hints[] for a slot label when there's more than one.
  const templateUrls = hasCalendarBlock
    ? calendarBlock.google_template_urls && calendarBlock.google_template_urls.length > 0
      ? calendarBlock.google_template_urls
      : calendarBlock.google_template_url
      ? [calendarBlock.google_template_url]
      : []
    : [];
  const templateSlotLabels =
    hasCalendarBlock && calendarBlock.time_hints && calendarBlock.time_hints.length === templateUrls.length
      ? calendarBlock.time_hints.map((hint) => hint.slot)
      : templateUrls.map(() => null);

  function handleTemplateLinkClick() {
    if (hasCalendarBlock && calendarBlock.dedupe_key) {
      markAddedToCalendarThisSession(calendarBlock.dedupe_key);
      setTemplateClicked(true);
    }
  }

  function openPreview() {
    setErrorMessage("");

    if (hasFixedDateTime) {
      setTitle(event.title);
      setEndTime(
        toTimeInputValue(
          new Date(fixedStartDate.getTime() + DEFAULT_DURATION_MINUTES * 60000)
        )
      );
    } else if (hasCalendarBlock) {
      // Read everything from the block — nothing recomputed.
      setTitle(calendarBlock.title || event.title);

      const hint = calendarBlock.time_hint;
      const firstWeekday =
        (calendarBlock.weekdays && calendarBlock.weekdays[0]) ||
        (event.weekday || "").trim().toLowerCase();

      const defaultDate = calendarBlock.first_date
        ? parseLocalDate(calendarBlock.first_date)
        : nextDateForWeekday(firstWeekday);

      const suggestedTime =
        hint?.start_local || suggestedStartTimeFromActivityWhen(event.activityWhen);
      const duration = calendarBlock.default_duration_minutes || DEFAULT_DURATION_MINUTES;
      const suggestedEnd = hint?.end_local || addMinutesToTimeString(suggestedTime, duration);

      setRecurStartDate(toDateInputValue(defaultDate));
      setRecurStartTime(suggestedTime);
      setEndTime(suggestedEnd);
    } else {
      setTitle(event.title);
      const defaultDate = nextDateForWeekday(event.weekday.trim().toLowerCase());
      const suggestedTime = suggestedStartTimeFromActivityWhen(event.activityWhen);
      setRecurStartDate(toDateInputValue(defaultDate));
      setRecurStartTime(suggestedTime);
      setEndTime(addMinutesToTimeString(suggestedTime, DEFAULT_DURATION_MINUTES));
    }

    setStep("preview");
  }

  function closeModal() {
    if (step === "sending") return; // don't let the user close mid-request
    setStep("closed");
  }

  function handleConfirm() {
    // AC5.2.4 — warn before silently creating a second entry for the same
    // event in this session. Prefer the backend's dedupe_key when there is
    // one, since it's shared with the template-link path above.
    const dedupeId = (hasCalendarBlock && calendarBlock.dedupe_key) || event.id;
    if (hasAddedToCalendarThisSession(dedupeId)) {
      setStep("duplicate");
      return;
    }
    submit();
  }

  async function submit() {
    setStep("sending");
    setErrorMessage("");

    const startDate = hasFixedDateTime
      ? fixedStartDate
      : combineDateAndTime(recurStartDate, recurStartTime);

    const endDate = hasFixedDateTime
      ? combineDateAndTime(event.dateLocal, endTime)
      : combineDateAndTime(recurStartDate, endTime);

    const recurrenceRule = hasFixedDateTime
      ? null
      : hasCalendarBlock && calendarBlock.rrule
      ? `RRULE:${calendarBlock.rrule}`
      : buildWeeklyRecurrenceRule(event.weekday);

    const descriptionOverride =
      hasCalendarBlock && calendarBlock.description_lines
        ? calendarBlock.description_lines.join("\n")
        : undefined;

    const dedupeId = (hasCalendarBlock && calendarBlock.dedupe_key) || event.id;

    try {
      const payload = buildCalendarEventPayload({
        title: title.trim() || event.title,
        startDate,
        endDate,
        venueName: hasCalendarBlock ? calendarBlock.location : event.venueName,
        venueAddress: hasCalendarBlock ? "" : event.venueAddress,
        venueHref: event.venueHref,
        facilities: event.facilities,
        recurrenceRule,
        descriptionOverride,
        publishedTimeQuote,
        checkedDateLabel,
        sourceLink: contactLink,
        contactLink,
      });

      const created = await createGoogleCalendarEvent(payload);

      markAddedToCalendarThisSession(dedupeId);
      setResultLink(created.htmlLink || "");
      setStep("success");
    } catch (error) {
      setErrorMessage(
        error.message || "Something went wrong adding this to your calendar."
      );
      setStep("error");
    }
  }

  const repeatsLabel = hasCalendarBlock
    ? formatWeekday((calendarBlock.weekdays && calendarBlock.weekdays[0]) || event.weekday)
    : formatWeekday(event.weekday);

  return (
    <>
      {hasCalendarBlock && templateUrls.length > 0 ? (
        <div className="calendar-quick-add">
          {templateUrls.map((url, index) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="event-action-link event-action-link--primary calendar-add-button"
              onClick={handleTemplateLinkClick}
            >
              <span aria-hidden="true">📅</span> Add to Google Calendar
              {templateSlotLabels[index] && templateSlotLabels[index] !== "main"
                ? ` (${templateSlotLabels[index]})`
                : ""}
            </a>
          ))}

          {calendarBlock.ics_url && (
            <a
              href={calendarBlock.ics_url}
              className="event-action-link event-action-link--secondary"
            >
              Download .ics
            </a>
          )}

          {templateClicked && (
            <p className="calendar-status-note calendar-added-note">
              Added — opened in a new tab. Click again only if you want a
              second copy.
            </p>
          )}

          <button
            type="button"
            className="calendar-secondary-link"
            onClick={openPreview}
          >
            Prefer to add it a different way?
          </button>
        </div>
      ) : (
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
      )}

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
                  {hasFixedDateTime
                    ? "Check the details below, then confirm — nothing is sent to Google until you do."
                    : "This activity repeats weekly. Confirm the day and time below — nothing is sent to Google until you do."}
                </p>

                <label className="calendar-field">
                  <span>Title</span>
                  <input
                    type="text"
                    value={title}
                    onChange={(domEvent) => setTitle(domEvent.target.value)}
                  />
                </label>

                {hasFixedDateTime ? (
                  <div className="calendar-field-row">
                    <div className="calendar-field calendar-field--readonly">
                      <span>Date</span>
                      <p>
                        {fixedStartDate.toLocaleDateString("en-AU", {
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
                        {fixedStartDate.toLocaleTimeString("en-AU", {
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
                ) : (
                  <>
                    <div className="calendar-field calendar-field--readonly">
                      <span>Repeats</span>
                      <p>
                        Every {repeatsLabel}
                        {!hasCalendarBlock && event.activityWhen
                          ? ` · ${event.activityWhen}`
                          : ""}
                      </p>
                    </div>

                    {hasCalendarBlock && calendarBlock.time_hint ? (
                      <p className="calendar-quote-block">
                        The publisher's description says:{" "}
                        <em>"{calendarBlock.time_hint.quote}"</em> — check the
                        time with the provider, then confirm it below.
                      </p>
                    ) : !hasCalendarBlock && publishedTimeQuote ? (
                      <p className="calendar-quote-block">
                        As published by the organiser (checked {checkedDateLabel}):{" "}
                        <em>"{publishedTimeQuote}"</em> — not confirmed by
                        SportAble. Check it, then set the time below.
                        {contactLink && (
                          <>
                            {" "}
                            <a href={contactLink} target="_blank" rel="noopener noreferrer">
                              View source ↗
                            </a>
                          </>
                        )}
                      </p>
                    ) : (
                      <p className="calendar-recurrence-note">
                        {hasCalendarBlock
                          ? "SportAble could not find a published time for this activity."
                          : "SportAble could not find a published time for this activity. Please confirm it before adding."}
                        {contactLink && (
                          <>
                            {" "}
                            <a href={contactLink} target="_blank" rel="noopener noreferrer">
                              Contact the organiser ↗
                            </a>
                          </>
                        )}
                      </p>
                    )}

                    <div className="calendar-field-row">
                      <label className="calendar-field">
                        <span>Starts from</span>
                        <input
                          type="date"
                          value={recurStartDate}
                          min={toDateInputValue(new Date())}
                          onChange={(domEvent) => setRecurStartDate(domEvent.target.value)}
                        />
                      </label>

                      <label className="calendar-field">
                        <span>Start time</span>
                        <input
                          type="time"
                          value={recurStartTime}
                          onChange={(domEvent) => setRecurStartTime(domEvent.target.value)}
                        />
                      </label>

                      <label className="calendar-field">
                        <span>End time</span>
                        <input
                          type="time"
                          value={endTime}
                          onChange={(domEvent) => setEndTime(domEvent.target.value)}
                        />
                      </label>
                    </div>
                  </>
                )}

                <div className="calendar-field calendar-field--readonly">
                  <span>Venue</span>
                  <p>
                    {hasCalendarBlock
                      ? calendarBlock.location
                      : `${event.venueName}${event.venueAddress ? `, ${event.venueAddress}` : ""}`}
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
                  {hasFixedDateTime
                    ? fixedStartDate.toLocaleDateString("en-AU", {
                        weekday: "long",
                        day: "numeric",
                        month: "long",
                      })
                    : `Every ${repeatsLabel}, starting ${new Date(
                        recurStartDate
                      ).toLocaleDateString("en-AU", { day: "numeric", month: "long" })}`}
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
