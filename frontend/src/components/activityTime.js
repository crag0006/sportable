const TIME_TOKEN = "\\d{1,2}[:.]\\d{2}\\s?(?:am|pm)|\\d{1,2}\\s?(?:am|pm)";
const TIME_RANGE_RE = new RegExp(
  `(?:${TIME_TOKEN})(?:\\s*(?:-|–|—|to|until|til)\\s*(?:${TIME_TOKEN}))?`,
  "i"
);

const MAX_QUOTE_LENGTH = 160;

function isSentenceBoundary(ch) {
  return ch === "\n" || ch === "." || ch === "!" || ch === "?";
}

export function extractPublishedTimeQuote(description) {
  if (!description || typeof description !== "string") return null;

  const match = TIME_RANGE_RE.exec(description);
  if (!match) return null;

  const matchStart = match.index;
  const matchEnd = matchStart + match[0].length;

  let start = matchStart;
  while (start > 0 && !isSentenceBoundary(description[start - 1])) start--;

  let end = matchEnd;
  while (end < description.length && !isSentenceBoundary(description[end]))
    end++;

  let quote = description.slice(start, end).trim();

  if (!quote || quote.length > MAX_QUOTE_LENGTH) {
    quote = description.slice(matchStart, matchEnd).trim();
  }

  return quote || null;
}

const ACTIVITY_WHEN_DEFAULTS = {
  morning: "09:00",
  "before school": "08:00",
  afternoon: "15:30",
  "after school": "15:30",
  evening: "18:00",
  night: "19:00"
};

export function suggestedStartTimeFromActivityWhen(activityWhen) {
  if (!activityWhen) return "09:00";
  const key = activityWhen.trim().toLowerCase();
  return ACTIVITY_WHEN_DEFAULTS[key] || "09:00";
}

export function todayCheckedLabel() {
  return new Date().toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

export function formatWeekday(weekday) {
  if (!weekday) return "";
  const trimmed = weekday.trim();
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1).toLowerCase();
}