
 // Matches time formats like 9am, 9:30am, or 10.30pm
const TIME_TOKEN = "\\d{1,2}[:.]\\d{2}\\s?(?:am|pm)|\\d{1,2}\\s?(?:am|pm)";

// Finds a single time or a time range in the event description
const TIME_RANGE_RE = new RegExp(
  `(?:${TIME_TOKEN})(?:\\s*(?:-|–|—|to|until|til)\\s*(?:${TIME_TOKEN}))?`,
  "i"
);

// Maximum number of characters allowed in a time quote
const MAX_QUOTE_LENGTH = 160;

// Checks whether a character marks the end of a sentence
function isSentenceBoundary(ch) {
  return ch === "\n" || ch === "." || ch === "!" || ch === "?";
}

// Finds the published time and returns the sentence containing it
export function extractPublishedTimeQuote(description) {
  if (!description || typeof description !== "string") return null;

  const match = TIME_RANGE_RE.exec(description);
  if (!match) return null;

  const matchStart = match.index;
  const matchEnd = matchStart + match[0].length;

  // Finds where the sentence starts
  let start = matchStart;
  while (start > 0 && !isSentenceBoundary(description[start - 1])) start--;

  // Finds where the sentence ends
  let end = matchEnd;
  while (end < description.length && !isSentenceBoundary(description[end]))
    end++;

  let quote = description.slice(start, end).trim();

  // Uses only the matched time if the sentence is too long
  if (!quote || quote.length > MAX_QUOTE_LENGTH) {
    quote = description.slice(matchStart, matchEnd).trim();
  }

  return quote || null;
}

// Default start times used when an exact time is not available
const ACTIVITY_WHEN_DEFAULTS = {
  morning: "09:00",
  "before school": "08:00",
  afternoon: "15:30",
  "after school": "15:30",
  evening: "18:00",
  night: "19:00"
};

// Suggests a start time based on the activity's time of day
export function suggestedStartTimeFromActivityWhen(activityWhen) {
  if (!activityWhen) return "09:00";

  const key = activityWhen.trim().toLowerCase();

  return ACTIVITY_WHEN_DEFAULTS[key] || "09:00";
}

// Returns today's date in Australian format
export function todayCheckedLabel() {
  return new Date().toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

// Converts weekday names into a readable format, such as Monday
export function formatWeekday(weekday) {
  if (!weekday) return "";

  const trimmed = weekday.trim();

  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1).toLowerCase();
}
