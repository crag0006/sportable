
import { getEventFacilityState } from "../pages/Events";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;


const CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events";

const FACILITY_LABELS = {
  accessible_toilet: "Accessible toilet",
  accessible_parking: "Accessible parking",
  accessible_transport_stop: "Accessible transport",
  accessible_change_facility: "Accessible change facility",
};

// --- Loading the Google Identity Services script, once ---------------------

let gisScriptPromise = null;

function loadGoogleIdentityScript() {
  if (gisScriptPromise) return gisScriptPromise;

  gisScriptPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) {
      resolve();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () =>
      reject(
        new Error(
          "Could not reach Google sign-in. Check your connection and try again."
        )
      );
    document.head.appendChild(script);
  });

  return gisScriptPromise;
}

// --- Getting an access token -----------------------------------------------

let tokenClient = null;
let cachedToken = null; // { accessToken, expiresAt }

function hasValidCachedToken() {
  return Boolean(cachedToken) && cachedToken.expiresAt > Date.now() + 30_000;
}

// Signs the user in to Google (if needed) and resolves an access token
// scoped to calendar.events. Each call reuses a still-valid cached token
// instead of prompting again.
export async function getGoogleAccessToken() {
  if (hasValidCachedToken()) {
    return cachedToken.accessToken;
  }

  if (!GOOGLE_CLIENT_ID) {
    throw new Error(
      "Google Calendar isn't set up yet for this site (missing client ID)."
    );
  }

  await loadGoogleIdentityScript();

  return new Promise((resolve, reject) => {
    if (!tokenClient) {
      tokenClient = window.google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: CALENDAR_SCOPE,
        callback: () => {}, // replaced per-request just below
      });
    }

    tokenClient.callback = (response) => {
      if (response.error) {
        reject(
          new Error(
            response.error === "access_denied" || response.error === "popup_closed"
              ? "Google sign-in was cancelled."
              : "Google sign-in failed. Please try again."
          )
        );
        return;
      }

      cachedToken = {
        accessToken: response.access_token,
        expiresAt: Date.now() + (response.expires_in || 3600) * 1000,
      };
      resolve(response.access_token);
    };

  
    tokenClient.requestAccessToken({
      prompt: hasValidCachedToken() ? "" : "consent",
    });
  });
}


const WEEKDAY_TO_RRULE_DAY = {
  sunday: "SU",
  monday: "MO",
  tuesday: "TU",
  wednesday: "WE",
  thursday: "TH",
  friday: "FR",
  saturday: "SA",
};

export function buildWeeklyRecurrenceRule(weekday) {
  const dayName = Array.isArray(weekday) ? weekday[0] : weekday;
  if (!dayName) return null;

  const byDay = WEEKDAY_TO_RRULE_DAY[dayName.trim().toLowerCase()];
  return byDay ? `RRULE:FREQ=WEEKLY;BYDAY=${byDay}` : null;
}

// --- Building the event payload ---------------------------------------------

function describeFacilityForCalendar(facility) {
  const label = FACILITY_LABELS[facility.type] || facility.type;
  const state = getEventFacilityState(facility);

  if (state === "at-venue") return `${label}: At the venue`;

  if (state === "within") {
    return facility.distance_m != null
      ? `${label}: ${facility.distance_m} m away`
      : `${label}: Unknown`;
  }

  if (state === "beyond") {
    return facility.distance_m != null
      ? `${label}: ${facility.distance_m} m away (beyond your selected limit)`
      : `${label}: Unknown`;
  }

  if (state === "absent") return `${label}: Not available`;

  return `${label}: Unknown`;
}


function buildDescription({
  venueHref,
  facilities,
  isRecurring,
  publishedTimeQuote,
  checkedDateLabel,
  sourceLink,
  contactLink,
}) {
  const lines = [];

  if (facilities && facilities.length > 0) {
    lines.push("Accessibility:");
    facilities.forEach((facility) => {
      lines.push("- " + describeFacilityForCalendar(facility));
    });
    lines.push("");
  }

  if (isRecurring) {
    if (publishedTimeQuote) {
      lines.push(
        `As published by the organiser (checked ${checkedDateLabel}): "${publishedTimeQuote}"`
      );
      if (sourceLink) lines.push(`Source: ${sourceLink}`);
      lines.push(
        "This time was not confirmed by SportAble — the time on this entry was entered by you."
      );
    } else {
      lines.push(
        "SportAble could not find a published time for this activity."
      );
      if (contactLink) lines.push(`Check with the organiser: ${contactLink}`);
      lines.push(
        "The time on this entry was entered by you, not confirmed by SportAble."
      );
    }
    lines.push("");
  }

  if (venueHref) {
    lines.push(`More details: ${venueHref}`);
    lines.push("");
  }

  lines.push("Added from SportAble Melbourne.");

  return lines.join("\n");
}


export function buildCalendarEventPayload({
  title,
  startDate,
  endDate,
  venueName,
  venueAddress,
  venueHref,
  facilities,
  recurrenceRule,
  publishedTimeQuote,
  checkedDateLabel,
  sourceLink,
  contactLink,
  descriptionOverride,
}) {
  const payload = {
    summary: title,
    location: [venueName, venueAddress].filter(Boolean).join(", "),
    description:
      descriptionOverride ||
      buildDescription({
        venueHref,
        facilities,
        isRecurring: Boolean(recurrenceRule),
        publishedTimeQuote,
        checkedDateLabel,
        sourceLink,
        contactLink,
      }),
    start: { dateTime: startDate.toISOString(), timeZone: "Australia/Melbourne" },
    end: { dateTime: endDate.toISOString(), timeZone: "Australia/Melbourne" },
  };

  if (recurrenceRule) {
    payload.recurrence = [recurrenceRule];
  }

  return payload;
}

// --- Creating the event -----------------------------------------------------

export async function createGoogleCalendarEvent(eventPayload) {
  const accessToken = await getGoogleAccessToken();

  const response = await fetch(
    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(eventPayload),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.error?.message ||
        "Google Calendar couldn't create this event. Please try again."
    );
  }

  return response.json(); 
}


const ADDED_EVENTS_KEY = "sportable-calendar-added-events";

function readAddedIds() {
  try {
    const raw = sessionStorage.getItem(ADDED_EVENTS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function hasAddedToCalendarThisSession(eventId) {
  return readAddedIds().includes(eventId);
}

export function markAddedToCalendarThisSession(eventId) {
  try {
    const ids = readAddedIds();
    if (!ids.includes(eventId)) {
      sessionStorage.setItem(
        ADDED_EVENTS_KEY,
        JSON.stringify([...ids, eventId])
      );
    }
  } catch {
    // Not critical — worst case, the duplicate warning just doesn't fire.
  }
}