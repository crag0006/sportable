import AppShell from '../components/AppShell'
import CollapsibleSearchPanel from '../components/CollapsibleSearchPanel'
import FacilityCard from '../components/FacilityCard'
import MiniMapLinkCard from '../components/MiniMapLinkCard'
import VenueHero from '../components/VenueHero'
import WeatherCard from '../components/WeatherCard'
import {
  searchPanelData,
  venueDetailData,
  venueFacilities,
  weatherData,
} from '../data/venueData'

export default function VenueDetailPage() {
  return (
    <AppShell
      backTo={venueDetailData.backTo}
      backLabel={venueDetailData.backLabel}
      headline={venueDetailData.sidebarHeadline}
      sidebarChildren={
        <>
          <CollapsibleSearchPanel data={searchPanelData} />
          <MiniMapLinkCard
            label={venueDetailData.mapPreview.label}
            caption={venueDetailData.mapPreview.caption}
            linkLabel={venueDetailData.mapPreview.linkLabel}
            to="/venues/1/directions"
          />
          <WeatherCard data={weatherData} />
        </>
      }
    >
      <VenueHero hero={venueDetailData.hero} />

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>{venueDetailData.facilitiesSectionTitle}</h3>
          </div>
        </div>

        <div className="facility-list">
          {venueFacilities.map((facility) => (
            <FacilityCard key={facility.id} facility={facility} />
          ))}
        </div>
      </section>
    </AppShell>
  )
}
