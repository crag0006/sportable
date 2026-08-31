import AppShell from '../components/AppShell'
import CollapsibleSearchPanel from '../components/CollapsibleSearchPanel'
import DirectionsHero from '../components/DirectionsHero'
import StaticRouteMap from '../components/StaticRouteMap'
import WeatherCard from '../components/WeatherCard'
import {
  directionsFacilities,
  directionsPageData,
  searchPanelData,
  weatherData,
} from '../data/venueData'

export default function DirectionsPage() {
  return (
    <AppShell
      backTo={directionsPageData.backTo}
      backLabel={directionsPageData.backLabel}
      headline={directionsPageData.sidebarHeadline}
      sidebarChildren={
        <>
          <CollapsibleSearchPanel data={searchPanelData} />
          <WeatherCard data={weatherData} />
        </>
      }
    >
      <DirectionsHero hero={directionsPageData.hero} />

      <section className="workspace">
        <StaticRouteMap
          mapData={directionsPageData.map}
          facilities={directionsFacilities}
          sectionTitle={directionsPageData.directionsSectionTitle}
          sectionBody={directionsPageData.directionsSectionBody}
        />
      </section>

      <section className="disclaimer-card">
        <h3>{directionsPageData.disclaimerTitle}</h3>
        <p>{directionsPageData.disclaimerBody}</p>
      </section>
    </AppShell>
  )
}
