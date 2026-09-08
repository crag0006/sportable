import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Landing from "./pages/LandingPage";
import DirectionsPage from './pages/DirectionsPage'
import HomePage from './pages/Home'
import VenueDetailPage from './pages/VenueDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Landing page with information about the app */}
        <Route path="/" element={<Landing />} />

        {/* Venue search page */}
        <Route path="/venues" element={<HomePage />} />

        <Route path="/venues/:id" element={<VenueDetailPage />} />
        <Route path="/venues/:id/directions" element={<DirectionsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}