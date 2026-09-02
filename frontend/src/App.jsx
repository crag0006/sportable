import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import DirectionsPage from './pages/DirectionsPage'
import Home from './pages/Home'
import VenueDetailPage from './pages/VenueDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/venues/:id" element={<VenueDetailPage />} />
        <Route path="/venues/:id/directions" element={<DirectionsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
