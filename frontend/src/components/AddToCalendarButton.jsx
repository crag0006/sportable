import { useEffect, useRef, useState } from "react";
import "./AddToCalendarButton.css";

import {
  buildCalendarEventPayload,
  buildWeeklyRecurrenceRule,
  createGoogleCalendarEvent,
  hasAddedToCalendarThisSession,
  markAddedToCalendarThisSession
} from "./googleCalendar";

import {
  extractPublishedTimeQuote,
  formatWeekday,
  suggestedStartTimeFromActivityWhen,
  todayCheckedLabel
} from "./activityTime";

// Default event duration is two hours
const DEFAULT_DURATION_MINUTES = 120;

const WEEKDAY_NAMES = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday"
];

// Converts 24-hour time into a readable format
function formatLocalTimeOfDay(hhmm) {
  if (!hhmm) return null;

  const [hours, minutes] = hhmm.split(":").map(Number);
  const date = new Date(2000, 0, 1, hours, minutes);

  return date
    .toLocaleTimeString("en-AU", {
      hour: "numeric",
      minute: "2-digit"
    })
    .toLowerCase();
}

// Converts a date object's time into HH:MM format
function toTimeInputValue(date) {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");

  return `${hours}:${minutes}`;
}

// Converts a date into YYYY-MM-DD format
function toDateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

// Combines the selected date and time
function combineDateAndTime(dateString, timeString) {
  return new Date(`${dateString}T${timeString}:00`);
}

// Adds the given number of minutes to a time
function addMinutesToTimeString(timeString, minutes) {
  const [hours, mins] = timeString.split(":").map(Number);
  const date = new Date(2000, 0, 1, hours, mins);

  date.setMinutes(date.getMinutes() + minutes);

  return toTimeInputValue(date);
}

// Finds the next date for the selected weekday
function nextDateForWeekday(weekdayName) {
  const targetIndex = WEEKDAY_NAMES.indexOf(weekdayName);

  if (targetIndex === -1) return new Date();

  const today = new Date();
  const diff = (targetIndex - today.getDay() + 7) % 7;
  const result = new Date(today);

  result.setDate(today.getDate() + diff);

  return result;
}

// Converts a date string into a date object
function parseLocalDate(dateString) {
  if (!dateString) return null;

  return new Date(`${dateString}T00:00:00`);
}

// Facility names displayed in the calendar preview
const FACILITY_LABELS = {
  accessible_toilet: "Accessible toilet",
  accessible_parking: "Accessible parking",
  accessible_transport_stop: "Accessible transport",
  accessible_change_facility: "Accessible change facility"
};

export default function AddToCalendarButton({ event }) {
  // Checks whether calendar details are provided by the backend
  const calendarBlock = event.calendarBlock || null;
  const hasCalendarBlock = Boolean(calendarBlock);

  // Checks if the event has a fixed date or repeats weekly
  const hasFixedDateTime = Boolean(event.dateLocal && event.timeLocal);
  const hasLegacyRecurrence = Boolean(event.weekday);

  // Checks whether the event can be added to a calendar
  const canAdd = hasCalendarBlock
    ? calendarBlock.exportable
    : hasFixedDateTime || hasLegacyRecurrence;

  // Stores the current calendar form details and status
  const [step, setStep] = useState("closed");
  const [title, setTitle] = useState(event.title);
  const [endTime, setEndTime] = useState("");
  const [recurStartDate, setRecurStartDate] = useState("");
  const [recurStartTime, setRecurStartTime] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [resultLink, setResultLink] = useState("");

  // Checks whether the calendar link was already used in this session
  const [templateClicked, setTemplateClicked] = useState(() =>
    hasCalendarBlock && calendarBlock.dedupe_key
      ? hasAddedToCalendarThisSession(calendarBlock.dedupe_key)
      : false
  );

  // Closes the calendar dropdown when clicking outside it
  const dropdownRef = useRef(null);

  useEffect(() => {
    function handleOutsideClick(domEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(domEvent.target)
      ) {
        dropdownRef.current.open = false;
      }
    }

    document.addEventListener("mousedown", handleOutsideClick);

    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  // Shows a message if the event cannot be added
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

  // Gets the event organiser's website or registration link
  const contactLink = event.registrationLink || event.externalLink || null;

  // Gets any published time information for older event records
  const publishedTimeQuote =
    !hasCalendarBlock && isRecurring
      ? extractPublishedTimeQuote(event.description)
      : null;

  const checkedDateLabel = todayCheckedLabel();

  // Gets a suitable label for a recurring event time
  function labelForTimeHint(hint) {
    if (!hint) return null;

    if (hint.slot && hint.slot !== "main") return hint.slot;

    if (hint.weekdays && hint.weekdays.length > 0) {
      return formatWeekday(hint.weekdays[0]);
    }

    return null;
  }

  // Creates calendar links when the backend uses the older format
  function buildLegacyTemplateLinks() {
    const urls =
      calendarBlock.google_template_urls &&
      calendarBlock.google_template_urls.length > 0
        ? calendarBlock.google_template_urls
        : calendarBlock.google_template_url
          ? [calendarBlock.google_template_url]
          : [];

    if (urls.length <= 1) {
      return urls.map((url) => ({ url, label: null }));
    }

    const hints = calendarBlock.time_hints || [];

    return urls.map((url, index) => {
      const hint = hints.length === urls.length ? hints[index] : null;
      const dayLabel = labelForTimeHint(hint);

      const timeLabel =
        hint && formatLocalTimeOfDay(hint.start_local)
          ? `${formatLocalTimeOfDay(hint.start_local)}${
              hint.end_local ? ` – ${formatLocalTimeOfDay(hint.end_local)}` : ""
            }`
          : null;

      return {
        url,
        label: [dayLabel, timeLabel].filter(Boolean).join(" · ") || null
      };
    });
  }

  // Uses the calendar links provided by the backend when available
  const templateLinks = hasCalendarBlock
    ? calendarBlock.google_template_links &&
      calendarBlock.google_template_links.length > 0
      ? calendarBlock.google_template_links.map((link) => ({
          url: link.url,
          label: link.label
        }))
      : buildLegacyTemplateLinks()
    : [];

  // Records that the user clicked a Google Calendar link
  function handleTemplateLinkClick() {
    if (hasCalendarBlock && calendarBlock.dedupe_key) {
      markAddedToCalendarThisSession(calendarBlock.dedupe_key);
      setTemplateClicked(true);
    }
  }

  // Opens the calendar preview with the available event details
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
      setTitle(calendarBlock.title || event.title);

      const hint = calendarBlock.time_hint;

      const firstWeekday =
        (calendarBlock.weekdays && calendarBlock.weekdays[0]) ||
        (event.weekday || "").trim().toLowerCase();

      const defaultDate = calendarBlock.first_date
        ? parseLocalDate(calendarBlock.first_date)
        : nextDateForWeekday(firstWeekday);

      const suggestedTime =
        hint?.start_local ||
        suggestedStartTimeFromActivityWhen(event.activityWhen);

      const duration =
        calendarBlock.default_duration_minutes || DEFAULT_DURATION_MINUTES;

      const suggestedEnd =
        hint?.end_local || addMinutesToTimeString(suggestedTime, duration);

      setRecurStartDate(toDateInputValue(defaultDate));
      setRecurStartTime(suggestedTime);
      setEndTime(suggestedEnd);
    } else {
      setTitle(event.title);

      const defaultDate = nextDateForWeekday(
        event.weekday.trim().toLowerCase()
      );

      const suggestedTime = suggestedStartTimeFromActivityWhen(
        event.activityWhen
      );

      setRecurStartDate(toDateInputValue(defaultDate));
      setRecurStartTime(suggestedTime);

      setEndTime(
        addMinutesToTimeString(suggestedTime, DEFAULT_DURATION_MINUTES)
      );
    }

    setStep("preview");
  }

  // Closes the calendar popup unless an event is being saved
  function closeModal() {
    if (step === "sending") return;

    setStep("closed");
  }

  // Checks for duplicate entries before adding the event
  function handleConfirm() {
    const dedupeId = (hasCalendarBlock && calendarBlock.dedupe_key) || event.id;

    if (hasAddedToCalendarThisSession(dedupeId)) {
      setStep("duplicate");
      return;
    }

    submit();
  }

  // Sends the event details to Google Calendar
  async function submit() {
    setStep("sending");
    setErrorMessage("");

    const startDate = hasFixedDateTime
      ? fixedStartDate
      : combineDateAndTime(recurStartDate, recurStartTime);

    const endDate = hasFixedDateTime
      ? combineDateAndTime(event.dateLocal, endTime)
      : combineDateAndTime(recurStartDate, endTime);

    // Adds a weekly repeat rule for recurring activities
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
      // Prepares the event information for Google Calendar
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
        contactLink
      });

      const created = await createGoogleCalendarEvent(payload);

      // Stores the result after the event is added successfully
      markAddedToCalendarThisSession(dedupeId);
      setResultLink(created.htmlLink || "");
      setStep("success");
    } catch (error) {
      // Shows an error message if the calendar request fails
      setErrorMessage(
        error.message || "Something went wrong adding this to your calendar."
      );

      setStep("error");
    }
  }

  const repeatsLabel = hasCalendarBlock
    ? formatWeekday(
        (calendarBlock.weekdays && calendarBlock.weekdays[0]) || event.weekday
      )
    : formatWeekday(event.weekday);

  return (
    <>
      {/* Shows the Google Calendar link when it is available */}
      {hasCalendarBlock && templateLinks.length > 0 ? (
        <div className="calendar-quick-add">
          {templateLinks.length === 1 ? (
            <a
              href={templateLinks[0].url}
              target="_blank"
              rel="noopener noreferrer"
              className="event-action-link event-action-link--primary calendar-add-button"
              onClick={handleTemplateLinkClick}
            >
              <span aria-hidden="true">📅</span> Add to Google Calendar
            </a>
          ) : (
            // Shows a dropdown when there are several event times
            <details className="calendar-add-dropdown" ref={dropdownRef}>
              <summary className="event-action-link event-action-link--primary calendar-add-button">
                <span aria-hidden="true">📅</span> Add to Google Calendar
              </summary>

              <div className="calendar-add-dropdown-menu" role="menu">
                {templateLinks.map((link, index) => (
                  <a
                    key={link.url}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    role="menuitem"
                    className="calendar-add-dropdown-item"
                    onClick={() => {
                      handleTemplateLinkClick();

                      if (dropdownRef.current) {
                        dropdownRef.current.open = false;
                      }
                    }}
                  >
                    <span className="calendar-add-dropdown-day">
                      {link.label || `Option ${index + 1}`}
                    </span>
                  </a>
                ))}
              </div>
            </details>
          )}

          {/* Allows users to download the calendar event file */}
          {calendarBlock.ics_url && (
            <a
              href={calendarBlock.ics_url}
              className="event-action-link event-action-link--secondary"
            >
              Download .ics
            </a>
          )}

          {/* Shows a message after a calendar link has been clicked */}
          {templateClicked && (
            <p className="calendar-status-note calendar-added-note">
              ✓ Added to your calendar
            </p>
          )}
        </div>
      ) : (
        // Opens the calendar preview when no direct link is available
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
            alignSelf: "center"
          }}
        >
          <span aria-hidden="true">📅</span> Add to Google Calendar
        </button>
      )}

      {/* Calendar popup */}
      {step !== "closed" && (
        <div
          className="calendar-modal-overlay"
          onClick={(domEvent) => {
            if (domEvent.target === domEvent.currentTarget) {
              closeModal();
            }
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
            {/* Shows the event details before adding to the calendar */}
            {step === "preview" && (
              <>
                <h3 className="calendar-modal-title">Add to Google Calendar</h3>

                <p className="calendar-modal-subtitle">
                  {hasFixedDateTime
                    ? "Check the details below, then confirm — nothing is sent to Google until you do."
                    : "This activity repeats weekly. Confirm the day and time below — nothing is sent to Google until you do."}
                </p>

                {/* Event title */}
                <label className="calendar-field">
                  <span>Title</span>
                  <input
                    type="text"
                    value={title}
                    onChange={(domEvent) => setTitle(domEvent.target.value)}
                  />
                </label>

                {/* Date and time fields for a fixed event */}
                {hasFixedDateTime ? (
                  <div className="calendar-field-row">
                    <div className="calendar-field calendar-field--readonly">
                      <span>Date</span>
                      <p>
                        {fixedStartDate.toLocaleDateString("en-AU", {
                          weekday: "short",
                          day: "numeric",
                          month: "short",
                          year: "numeric"
                        })}
                      </p>
                    </div>

                    <div className="calendar-field calendar-field--readonly">
                      <span>Start time</span>
                      <p>
                        {fixedStartDate.toLocaleTimeString("en-AU", {
                          hour: "numeric",
                          minute: "2-digit"
                        })}
                      </p>
                    </div>

                    <label className="calendar-field">
                      <span>End time</span>
                      <input
                        type="time"
                        value={endTime}
                        onChange={(domEvent) =>
                          setEndTime(domEvent.target.value)
                        }
                      />
                    </label>
                  </div>
                ) : (
                  <>
                    {/* Weekly repeat details */}
                    <div className="calendar-field calendar-field--readonly">
                      <span>Repeats</span>
                      <p>
                        Every {repeatsLabel}
                        {!hasCalendarBlock && event.activityWhen
                          ? ` · ${event.activityWhen}`
                          : ""}
                      </p>
                    </div>

                    {/* Shows the published time when available */}
                    {hasCalendarBlock && calendarBlock.time_hint ? (
                      <p className="calendar-quote-block">
                        The publisher's description says:{" "}
                        <em>"{calendarBlock.time_hint.quote}"</em> — check the
                        time with the provider, then confirm it below.
                      </p>
                    ) : !hasCalendarBlock && publishedTimeQuote ? (
                      <p className="calendar-quote-block">
                        As published by the organiser (checked{" "}
                        {checkedDateLabel}): <em>"{publishedTimeQuote}"</em> —
                        not confirmed by SportAble. Check it, then set the time
                        below.
                        {contactLink && (
                          <>
                            {" "}
                            <a
                              href={contactLink}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              View source ↗
                            </a>
                          </>
                        )}
                      </p>
                    ) : (
                      // Asks users to confirm the time if it is not published
                      <p className="calendar-recurrence-note">
                        {hasCalendarBlock
                          ? "SportAble could not find a published time for this activity."
                          : "SportAble could not find a published time for this activity. Please confirm it before adding."}

                        {contactLink && (
                          <>
                            {" "}
                            <a
                              href={contactLink}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              Contact the organiser ↗
                            </a>
                          </>
                        )}
                      </p>
                    )}

                    {/* Date and time inputs for recurring activities */}
                    <div className="calendar-field-row">
                      <label className="calendar-field">
                        <span>Starts from</span>
                        <input
                          type="date"
                          value={recurStartDate}
                          min={toDateInputValue(new Date())}
                          onChange={(domEvent) =>
                            setRecurStartDate(domEvent.target.value)
                          }
                        />
                      </label>

                      <label className="calendar-field">
                        <span>Start time</span>
                        <input
                          type="time"
                          value={recurStartTime}
                          onChange={(domEvent) =>
                            setRecurStartTime(domEvent.target.value)
                          }
                        />
                      </label>

                      <label className="calendar-field">
                        <span>End time</span>
                        <input
                          type="time"
                          value={endTime}
                          onChange={(domEvent) =>
                            setEndTime(domEvent.target.value)
                          }
                        />
                      </label>
                    </div>
                  </>
                )}

                {/* Venue location */}
                <div className="calendar-field calendar-field--readonly">
                  <span>Venue</span>
                  <p>
                    {hasCalendarBlock
                      ? calendarBlock.location
                      : `${event.venueName}${
                          event.venueAddress ? `, ${event.venueAddress}` : ""
                        }`}
                  </p>
                </div>

                {/* Accessibility facilities included in the event */}
                {event.facilities && event.facilities.length > 0 && (
                  <div className="calendar-field calendar-field--readonly">
                    <span>
                      Accessibility (included in the event description)
                    </span>

                    <ul className="calendar-facility-list">
                      {event.facilities.map((facility) => (
                        <li key={facility.type}>
                          {FACILITY_LABELS[facility.type] || facility.type}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Cancel or confirm the calendar event */}
                <div className="calendar-modal-actions">
                  <button
                    type="button"
                    className="calendar-btn-secondary"
                    onClick={closeModal}
                  >
                    Cancel
                  </button>

                  <button
                    type="button"
                    className="calendar-btn-primary"
                    onClick={handleConfirm}
                  >
                    Add to calendar
                  </button>
                </div>
              </>
            )}

            {/* Warns the user if the event was already added */}
            {step === "duplicate" && (
              <>
                <h3 className="calendar-modal-title">Already added</h3>

                <p className="calendar-modal-subtitle">
                  You've already added "{event.title}" to your Google Calendar
                  during this visit. Adding it again will create a second,
                  separate entry.
                </p>

                <div className="calendar-modal-actions">
                  <button
                    type="button"
                    className="calendar-btn-secondary"
                    onClick={() => setStep("preview")}
                  >
                    Cancel
                  </button>

                  <button
                    type="button"
                    className="calendar-btn-primary"
                    onClick={submit}
                  >
                    Add anyway
                  </button>
                </div>
              </>
            )}

            {/* Loading message while adding the event */}
            {step === "sending" && (
              <div className="calendar-status">
                <div className="calendar-spinner" aria-hidden="true" />
                <p>Adding to your Google Calendar…</p>
              </div>
            )}

            {/* Confirmation shown after the event is added */}
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
                        month: "long"
                      })
                    : `Every ${repeatsLabel}, starting ${new Date(
                        recurStartDate
                      ).toLocaleDateString("en-AU", {
                        day: "numeric",
                        month: "long"
                      })}`}
                </p>

                {/* Link to open the newly created calendar event */}
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

                <button
                  type="button"
                  className="calendar-btn-secondary"
                  onClick={closeModal}
                >
                  Done
                </button>
              </div>
            )}

            {/* Shows an error if the event could not be added */}
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
                  <button
                    type="button"
                    className="calendar-btn-secondary"
                    onClick={closeModal}
                  >
                    Close
                  </button>

                  <button
                    type="button"
                    className="calendar-btn-primary"
                    onClick={() => setStep("preview")}
                  >
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
