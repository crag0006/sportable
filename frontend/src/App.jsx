import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Landing from "./pages/LandingPage";
import DirectionsPage from './pages/DirectionsPage'
import HomePage from './pages/Home'
import VenueDetailPage from './pages/VenueDetailPage'
import PasswordGate from './pages/Passwordgate'
import Events from './pages/Events'
import SavedEvents from './pages/SavedEvents'

export default function App() {
  return (
    <PasswordGate>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/venues" element={<HomePage />} />
          <Route path="/venues/:id" element={<VenueDetailPage />} />
          <Route path="/venues/:id/directions" element={<DirectionsPage />} />
          <Route path="/events" element={<Events />} />
          <Route path="/saved-events" element={<SavedEvents />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </PasswordGate>
  )
}
