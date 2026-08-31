import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import DirectionsPage from './pages/DirectionsPage'
import HomePage from './pages/HomePage'
import VenueDetailPage from './pages/VenueDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/venues/1" element={<VenueDetailPage />} />
        <Route path="/venues/1/directions" element={<DirectionsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
