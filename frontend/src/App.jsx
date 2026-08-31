import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import DirectionsPage from './pages/DirectionsPage'
import VenueDetailPage from './pages/VenueDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/venues/1" replace />} />
        <Route path="/venues/1" element={<VenueDetailPage />} />
        <Route path="/venues/1/directions" element={<DirectionsPage />} />
      </Routes>
    </BrowserRouter>
  )
}
