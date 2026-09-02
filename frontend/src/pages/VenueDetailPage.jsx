import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getConfig, getVenue } from "../api/venues";
import FacilityCard from "../components/FacilityCard";
import VenueHero from "../components/VenueHero";
import { FACILITY_INFO, VENUES as HOME_VENUES } from "../data/homepageVenues";
import { venueFacilities, venueDetailData } from "../data/venueData";

// This page shows all the details for ONE venue — the page you land on
// after clicking "View venue" on a search result card.

// Each amenity (toilet, parking, transport stop, change facility) needs
// a small icon next to it. This says which icon to use for each one.
const AMENITY_CONFIG = {
  toilet: { icon: "toilet" },
  parking: { icon: "parking" },
  stop: { icon: "transport" },
  change: { icon: "change" },
};

// Turns the list "venueFacilities" into a lookup object, so we can find
// one facility's backup text quickly by its id.
const FACILITY_CONTENT_FALLBACK = Object.fromEntries(
  venueFacilities.map((item) => [item.id, item])
);

// Builds the address line shown under the venue name.
function formatAddress(venue) {
  if (venue.address) {
    return venue.address;
  }

  const suburbAndPostcode = [venue.suburb, venue.postcode]
    .filter(Boolean)
    .join(" ");

  if (suburbAndPostcode) {
    return suburbAndPostcode;
  }

  return "Address not published";
}

// Looks up the backup text for one facility, in case the backend didn't
// send us anything useful for it.
function getFacilityFallback(key) {
  return FACILITY_CONTENT_FALLBACK[key] ?? null;
}

// Works out the status of one amenity (toilet, parking, etc):
//   - "none" from the backend = "unknown" to us (nothing published)
//   - "absent" = someone checked, it isn't there
//   - "confirmed" = it's at the venue itself
//   - otherwise, compare the distance to the selected limit
function getAmenityState(item, limit) {
  if (!item || item.state === "none") {
    return "unknown";
  }

  if (item.state === "absent") {
    return "absent";
  }

  if (item.state === "confirmed") {
    return "at_venue";
  }

  const facilityDistance = Number(item.distance);
  const selectedLimit = Number(limit);

  if (limit === "" || Number.isNaN(selectedLimit) || facilityDistance <= selectedLimit) {
    return "within";
  }

  return "beyond";
}

// The short text shown in the coloured pill next to each facility name.
function getAmenitySummaryText(item, state) {
  if (state === "at_venue") {
    return "At the venue";
  }

  if (state === "within") {
    return `${item.distance} m away`;
  }

  if (state === "beyond") {
    return `${item.distance} m away — beyond your limit`;
  }

  if (state === "absent") {
    return "Not available";
  }

  return "No published information — check with the venue";
}

// Builds the "Venue summary" and "Nearest recorded facility" boxes shown
// at the top of the page, under the venue name.
function buildSummary(venue) {
  const amenities = venue.amenities ?? {};
  const sentences = [];

  if (amenities.toilet?.state === "confirmed") {
    sentences.push("Accessible toilet at the venue.");
  }

  if (amenities.parking?.state === "confirmed") {
    sentences.push("Accessible parking at the venue.");
  }

  if (amenities.change?.state === "recorded" && amenities.change.distance) {
    sentences.push(`Nearest change facility ${amenities.change.distance} m away.`);
  }

  if ((venue.unpublished ?? []).some((item) => item.key === "enter")) {
    sentences.push("Step-free entry is not published.");
  }

  const panels = [];

  if (sentences.length > 0) {
    panels.push({
      label: "Venue summary",
      body: sentences.join(" "),
    });
  }

  const recordedFacilities = Object.values(amenities).filter(
    (item) => item?.state === "recorded" && item?.distance
  );

  const nearestRecorded = recordedFacilities.sort(
    (firstItem, secondItem) => firstItem.distance - secondItem.distance
  )[0];

  if (nearestRecorded) {
    panels.push({
      label: "Nearest recorded facility",
      emphasis: `${nearestRecorded.distance} m`,
      body: nearestRecorded.name || "Published nearby facility",
    });
  }

  return panels;
}

// Builds the one-line description shown under each facility's name.
function buildDescription(amenity, defaultLimit, fallbackFacility) {
  if (!amenity || amenity.state === "none") {
    return (
      fallbackFacility?.description ??
      "No published information. This is not a no — nobody has published data for this venue."
    );
  }

  if (amenity.state === "confirmed" && amenity.source?.name) {
    return `Recorded at the venue by ${amenity.source.name}.`;
  }

  if (amenity.state === "confirmed") {
    return fallbackFacility?.description ?? "Recorded at the venue.";
  }

  if (amenity.state === "recorded" && amenity.location === "public_nearby") {
    if (amenity.distance > defaultLimit) {
      return `Nearest published facility is ${amenity.distance} m away — beyond your ${defaultLimit} m limit.`;
    }

    const nameText = amenity.name ? `, at ${amenity.name}` : "";
    return `Nearest published facility is ${amenity.distance} m away${nameText}.`;
  }

  if (amenity.state === "recorded" && amenity.distance) {
    if (amenity.distance > defaultLimit) {
      return `Nearest published facility is ${amenity.distance} m away — beyond your ${defaultLimit} m limit.`;
    }

    return `Nearest published facility is ${amenity.distance} m away.`;
  }

  if (amenity.state === "absent") {
    return "The venue's own record says this is not available.";
  }

  return "";
}

// Builds the full list of facility cards for one venue.
function buildFacilityCards(venue, defaultLimit) {
  const cards = [];
  const amenities = venue.amenities ?? {};
  const limitValue = String(defaultLimit);

  Object.entries(AMENITY_CONFIG).forEach(([key, config]) => {
    const amenity = amenities[key];
    const homeInfo = FACILITY_INFO[key];
    const state = getAmenityState(amenity, limitValue);
    const fallbackFacility = getFacilityFallback(key);

    cards.push({
      id: key,
      title: homeInfo?.fullName ?? homeInfo?.name ?? key,
      description: buildDescription(amenity, defaultLimit, fallbackFacility),
      pillText: getAmenitySummaryText(amenity, state),
      state: state,
      icon: config.icon,
    });
  });

  const missingEntryInfo = (venue.unpublished ?? []).find(
    (item) => item.key === "enter"
  );

  if (missingEntryInfo) {
    cards.push({
      id: missingEntryInfo.key,
      title: missingEntryInfo.label,
      description: missingEntryInfo.reason,
      icon: "ramp",
      state: "unknown",
    });
  }

  return cards;
}

// Used only if the real backend can't be reached — builds a simple hero
// section from the old sample data instead.
function buildFallbackHero(venue) {
  return {
    eyebrow: "Venue detail",
    title: venue.name,
    address: formatAddress(venue),
    badge: venue.distance ? `${venue.distance} km from current search` : "",
    tags: [...(venue.sports ?? []), venue.surface].filter(Boolean),
    panels: venueDetailData.hero.panels,
  };
}

function VenueDetailPage() {
  // Reads the venue id straight out of the web address.
  const { id } = useParams();

  const [venue, setVenue] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState("");

  // If the real backend request fails, fall back to the old sample data.
  const fallbackVenue = useMemo(
    () => HOME_VENUES.find((item) => String(item.id) === String(id)) ?? null,
    [id]
  );

  const displayVenue = venue ?? fallbackVenue;

  // As soon as the page opens (or the id changes), ask the backend for
  // this venue's details and the distance settings.
  useEffect(() => {
    let didCancel = false;

    Promise.all([getVenue(id), getConfig()])
      .then(([venueBody, configBody]) => {
        if (didCancel) {
          return;
        }

        setVenue(venueBody);
        setConfig(configBody);
        setError("");
      })
      .catch((requestError) => {
        if (didCancel) {
          return;
        }

        setError(requestError.message);
      });

    return () => {
      didCancel = true;
    };
  }, [id]);

  const heroData = useMemo(() => {
    if (!venue) {
      if (fallbackVenue) {
        return buildFallbackHero(fallbackVenue);
      }

      return venueDetailData.hero;
    }

    return {
      eyebrow: "Venue detail",
      title: venue.name,
      address: formatAddress(venue),      
      tags: [...(venue.sports ?? []), venue.surface, venue.lga].filter(Boolean),
      panels: buildSummary(venue),
    };
  }, [fallbackVenue, venue]);

  const facilities = useMemo(() => {
    if (!displayVenue) {
      return [];
    }

    return buildFacilityCards(displayVenue, config?.default_distance_m ?? 500);
  }, [config, displayVenue]);

  return (
    <div className="venue-page">
      {/* Slim top bar — logo on the left, back button on the right.
          This replaces the old tall sidebar that left empty space. */}
      <header className="venue-topbar">
        <div className="venue-topbar-inner">
          <div className="venue-brand">
            <svg
              width="34"
              height="34"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="11" cy="4" r="2" />
              <path d="M11 8v6h5l3 6" />
              <path d="M15.5 14a5.5 5.5 0 1 1-6-5.48" />
            </svg>

            <div>
              <div className="venue-brand-name">SportAble</div>
              <div className="venue-brand-tagline">Know more. Play more.</div>
            </div>
          </div>

          <Link className="venue-back-link" to={venueDetailData.backTo}>
            ‹ {venueDetailData.backLabel}
          </Link>
        </div>
      </header>

      {/* The venue's details, now using the full width of the page */}
      <main className="venue-content">
        {/* A real photo banner, so the page has some visual life to it */}
  <div className="venue-banner">
    <div className="venue-banner-overlay">
      <p className="venue-banner-text">No more maybes — every step, mapped out.</p>
    </div>
  </div>
        <VenueHero hero={heroData} venueId={id} />

        {error && !fallbackVenue && (
          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>Venue information unavailable</h3>
              </div>
            </div>
            <p>{error}</p>
          </section>
        )}

        {facilities.length > 0 && (
          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>{venueDetailData.facilitiesSectionTitle}</h3>
              </div>
            </div>

            <div className="facility-list">
              {facilities.map((facility) => (
                <FacilityCard key={facility.id} facility={facility} />
              ))}
            </div>
          </section>
        )}
        {/* A general reminder, since accessibility details can change and
    some information on this page may be incomplete */}
{facilities.length > 0 && (
  <section className="disclaimer-card">
    <h3>Always double-check with the venue</h3>
    <p>
      Accessibility details shown here may be incomplete or out of date.
      For more clarification and further information, please contact
      the venue directly.
    </p>
  </section>
)}
      </main>
    </div>
  );
}

export default VenueDetailPage;