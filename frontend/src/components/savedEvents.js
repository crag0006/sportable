const SAVED_EVENTS_KEY = "sportable-saved-events";

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

function writeSavedEvents(list) {
  try {
    sessionStorage.setItem(SAVED_EVENTS_KEY, JSON.stringify(list));
  } catch {
    // Saving is a nice-to-have; if storage is full or unavailable, fail quietly.
  }
}

export function isEventSaved(eventId) {
  return getSavedEvents().some((item) => item.id === eventId);
}

// entry: { id, title, sport, dateTimeLabel, suburb, venueName }
export function addSavedEvent(entry) {
  const current = getSavedEvents();
  if (current.some((item) => item.id === entry.id)) return current;

  const next = [...current, entry];
  writeSavedEvents(next);
  return next;
}

export function removeSavedEvent(eventId) {
  const next = getSavedEvents().filter((item) => item.id !== eventId);
  writeSavedEvents(next);
  return next;
}

// Builds a plain-text summary for AC4.3.5's Export — event name, date/time,
// venue, one per line. Plain text rather than CSV/PDF so it opens straight
// in any text editor or email with no extra library needed.
export function buildSavedEventsExportText(list) {
  if (list.length === 0) return "No saved events.";

  const lines = list.map(
    (item) =>
      `${item.title} — ${item.dateTimeLabel || "Date to be confirmed"} — ${item.venueName}`
  );

  return ["Saved events (SportAble Melbourne)", "", ...lines].join("\n");
}