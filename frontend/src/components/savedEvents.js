// Key used to store saved events in the browser session
const SAVED_EVENTS_KEY = "sportable-saved-events";

// Gets the list of saved events from session storage
export function getSavedEvents() {
  try {
    const raw = sessionStorage.getItem(SAVED_EVENTS_KEY);
    if (!raw) return [];

    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

// Saves the updated list of events in session storage
function writeSavedEvents(list) {
  try {
    sessionStorage.setItem(SAVED_EVENTS_KEY, JSON.stringify(list));
  } catch {
    // Continues without saving if session storage is unavailable
  }
}

// Checks whether an event is already saved
export function isEventSaved(eventId) {
  return getSavedEvents().some((item) => item.id === eventId);
}

// Adds an event to the saved list if it is not already there
export function addSavedEvent(entry) {
  const current = getSavedEvents();

  if (current.some((item) => item.id === entry.id)) return current;

  const next = [...current, entry];
  writeSavedEvents(next);

  return next;
}

// Removes the selected event from the saved list
export function removeSavedEvent(eventId) {
  const next = getSavedEvents().filter((item) => item.id !== eventId);

  writeSavedEvents(next);
  return next;
}

// Creates a text summary of saved events for exporting
export function buildSavedEventsExportText(list) {
  if (list.length === 0) return "No saved events.";

  const lines = list.map(
    (item) =>
      `${item.title} — ${item.dateTimeLabel || "Date to be confirmed"} — ${item.venueName}`
  );

  return ["Saved events (SportAble Melbourne)", "", ...lines].join("\n");
}
