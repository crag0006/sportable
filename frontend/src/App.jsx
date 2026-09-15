import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Landing from "./pages/LandingPage";
import DirectionsPage from './pages/DirectionsPage'
import HomePage from './pages/Home'
import VenueDetailPage from './pages/VenueDetailPage'
import Passwordgate from './pages/Passwordgate'
import Events from './pages/Events'

export default function App() {
  return (
    <Passwordgate>
    <BrowserRouter>
      <Routes>
        {/* Landing page with information about the app */}
        <Route path="/" element={<Landing />} />

        {/* Venue search page */}
        <Route path="/venues" element={<HomePage />} />

        <Route path="/events" element={<Events />} />

        <Route path="/venues/:id" element={<VenueDetailPage />} />
        <Route path="/venues/:id/directions" element={<DirectionsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
    </Passwordgate>
  )
}